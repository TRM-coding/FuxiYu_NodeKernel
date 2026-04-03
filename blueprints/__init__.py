from flask import Blueprint, jsonify, request
from ..utils.CheckKeys import get_verified_msg
from ..utils.Container import Container
from ..services.container_service import (
    create_container,
    remove_container,
    add_collaborator,
    remove_collaborator,
	update_role,
	start_container,
	stop_container,
	restart_container,
	get_last_ssh_connect_time
)
import threading
from .. import extensions
from ..constant import ROLE
import docker

# debug
# success = 1

api_bp = Blueprint("api", __name__, url_prefix="/api")

# 为的是将contaienr_status检查的特殊情况局限在创作过程
creation_status = {}
# 通用的操作状态追踪（start/stop/restart）
action_status = {}

def _set_action_status(container_name: str, action: str, status: str, error_reason: str | None = None):
	action_status[container_name] = {"action": action, "status": status, "error_reason": error_reason}

def _get_action_status(container_name: str):
	return action_status.get(container_name)

def _clear_action_status(container_name: str):
	action_status.pop(container_name, None)


# Helper wrappers to mirror create behavior and keep special-case handling centralized
def mark_creation_status(container_name: str, status: str, error_reason: str | None = None):
	creation_status[container_name] = {"status": status, "error_reason": error_reason}

def clear_creation_status(container_name: str):
	creation_status.pop(container_name, None)

def mark_start_status(container_name: str, status: str, error_reason: str | None = None):
	_set_action_status(container_name, 'start', status, error_reason)

def mark_stop_status(container_name: str, status: str, error_reason: str | None = None):
	_set_action_status(container_name, 'stop', status, error_reason)

def mark_restart_status(container_name: str, status: str, error_reason: str | None = None):
	_set_action_status(container_name, 'restart', status, error_reason)


'''
通信数据格式：
发送格式：
{
	"message":{
		"owner_name":"xxxx",
		"config":
		{
			"gpu_list":[0,1,2,...], #字段为空就是CPU机器
			"cpu_number":20,
			"memory":16,#GB
			"shared_memory":32,#GB
			"name":'example',
			"port":0,
			"image":"ubuntu24.04"
		}
		"public_key":"xxxx" # 可选，提供用户公钥以便容器内配置免密登录
	},
	"signature":"xxxxxx"
}
返回格式：
{
	success: [0|1],
	"container_id": container_id,
	"container_name": container_name
}
'''
@api_bp.post("/create_container")
def Create_container():
	print("Create_container Called")
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400
    

	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
    
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401
    
	# 提取消息配置
	owner_name = verified_msg.get("owner_name")
	config = verified_msg.get("config")
	public_key = verified_msg.get("public_key", None)
    
	try:
		cfg = Container.Config_info(**config)
	except Exception as e:
		return jsonify({"error": f"invalid config: {e}", "error_reason": "invalid_config"}), 400
	# ensure docker client so we can pre-check container name collisions
	if extensions.docker_client is None:
		try:
			extensions.init_docker()
		except Exception as e:
			return jsonify({"error": f"docker init failed: {e}", "error_reason": "docker_init_failed"}), 500

	# 额外预检：检查是否已存在同名容器，避免创建后才发现冲突
	try:
		existing = None
		try:
			existing = extensions.docker_client.containers.get(cfg.name)
		except docker.errors.NotFound:
			existing = None
		if existing is not None:
			return jsonify({"success": 0, "error": f"container {cfg.name} already exists", "error_reason": "container_exists", "container_name": cfg.name}), 409
	except Exception as e:
		# if we can't contact docker, return an error
		return jsonify({"success": 0, "error": f"docker check failed: {e}", "error_reason": "docker_check_failed"}), 500
	# spawn background thread to perform actual creation and return early
	def _bg_create(o_name, cfg_obj):
			try:
				# mark as creating
				creation_status[cfg_obj.name] = {"status": "creating"}
				create_container(o_name, cfg_obj, public_key=public_key)
				# creation succeeded -> remove tracking entry
				creation_status.pop(cfg_obj.name, None) # 使得创建后的容器状态查询可以直接从docker获取最新状态，而不是被卡在"creating"里
			except Exception as e:
				# record failure so /container_status can surface it to the controller
				print("create_container error:", e)
				creation_status[cfg_obj.name] = {"status": "failed", "error_reason": str(e)}


	try:
		t = threading.Thread(target=_bg_create, args=(owner_name, cfg))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "background_thread_failed"}), 500


	print("SUCCESS")
    
	return jsonify({
		"success": 1,
		"container_status": "creating",
		"container_name": cfg.name
	}), 200

# 由于部分内容需要api这个地方直接调用。并未将这个方法单独放到services里
@api_bp.post("/container_status")
def Container_status():
	'''
	通信数据格式：
	发送格式：
	{
		"message":{
			"config":
			{
				"container_name":"xxxx"
			}
		},
		"signature":"xxxxxx"
	}
	'''
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error":"invalid json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401
	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name", "error_reason": "missing_container_name"}), 400

	# ensure docker client
	if extensions.docker_client is None:
		try:
			extensions.init_docker()
		except Exception as e:
			return jsonify({"success": 0, "error": f"docker init failed: {e}"}), 500

	try:
		# docker SDK allows get by name
		# if there is an async failure/ongoing action recorded for this container name, return that first
		status_info = creation_status.get(container_name)
		if status_info is not None:
			if status_info.get("status") == "failed":
				return jsonify({"success": 0, "container_status": "failed", "error": "creation failed", "error_reason": status_info.get("error_reason")}), 200
			elif status_info.get("status") == "creating":
				return jsonify({"success": 1, "container_status": "creating", "container_name": container_name}), 200

		# check start/stop/restart async actions
		ainfo = _get_action_status(container_name)
		if ainfo is not None:
			st = ainfo.get('status')
			act = ainfo.get('action')
			if st == 'failed':
				return jsonify({"success": 0, "container_status": "failed", "error": f"{act} failed", "error_reason": ainfo.get('error_reason')}), 200
			else:
				# return the in-progress or terminal status reported by the action tracker
				return jsonify({"success": 1, "container_status": st, "container_name": container_name}), 200

		container = extensions.docker_client.containers.get(container_name)
		state = None
		try:
			state = container.attrs.get('State', {}).get('Status')
		except Exception:
			state = getattr(container, 'status', None)

		if state is None:
			status_out = "unknown"
		elif state.lower() == 'running':
			# additional readiness checks: ensure sshd is listening and authorized_keys exists
			def _exec_check(cmd: str) -> bool:
				try:
					r = container.exec_run(["/bin/sh", "-c", cmd], user="root")
					return getattr(r, 'exit_code', r[0]) == 0
				except Exception:
					return False

			# try multiple ways to detect ssh listening (ss/netstat/ps/pgrep)
			ssh_listening = False
			for c in ["ss -ltn | grep :22", "netstat -ltn | grep :22", "pgrep -f sshd", "ps aux | grep [s]shd"]:
				if _exec_check(c):
					ssh_listening = True
					break

			# check authorized_keys exists and is non-empty
			#auth_ok = _exec_check("test -s /root/.ssh/authorized_keys")

			if ssh_listening:
				status_out = "online"
			else:
				# container running but service not yet ready
				status_out = "starting"
		elif state.lower() in ('created', 'restarting', 'starting'):
			status_out = "starting"
		elif state.lower() in ('exited', 'dead'):
			status_out = "offline"
		else:
			status_out = str(state).lower()

		print(f"Container '{container_name}' status: {status_out}")

		return jsonify({"success": 1, "container_status": status_out, "container_name": container_name}), 200
	except docker.errors.NotFound:
		return jsonify({"success": 0, "error": "container not found", "error_reason": "not_found", "container_name": container_name}), 404
	except Exception as e:
		return jsonify({"success": 0, "error": str(e), "error_reason": "internal_error"}), 500


'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx"
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": 0|1,
	"container_name": "xxxx",
	"last_ssh_connect_time": "xxxx"
}
'''
@api_bp.post("/container_last_ssh_time")
def Container_last_ssh_time():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error":"invalid json", "error_reason": "invalid_json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401

	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name", "error_reason": "missing_container_name"}), 400

	try:
		last_time = get_last_ssh_connect_time(container_name)
		if last_time is None:
			return jsonify({
				"success": 0,
				"container_name": container_name,
				"error": "last ssh connect time not found",
				"error_reason": "not_found"
			}), 404
		return jsonify({
			"success": 1,
			"container_name": container_name,
			"last_ssh_connect_time": last_time
		}), 200
	except Exception as e:
		return jsonify({"success": 0, "error": str(e), "error_reason": "internal_error"}), 500


# Minimal machine status endpoint for controller health checks
@api_bp.post("/machine_status")
def Machine_status():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error": "invalid json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401

	# Best-effort: ensure docker client initialized; if it fails, still respond but mark non-ideal
	try:
		if extensions.docker_client is None:
			extensions.init_docker()
	except Exception as e:
		# return success but indicate docker init failed
		return jsonify({"success": 0, "error": f"docker init failed: {e}", "error_reason": "docker_init_failed"}), 500

	# If everything looks OK, report online. Keep response minimal to be fast.
	return jsonify({"success": 1, "machine_status": "online"}), 200

'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx"
		}
	},
	"signature":"xxxxxx"
}

返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/remove_container")
def Remove_container():
	recived_data = request.get_json(silent=True)
	print("Remove container called.")
	if not recived_data:
		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401
	
	# 提取消息类型和配置（防御性处理：可能没有 config）
	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"error": "missing container_name", "error_reason": "missing_container_name"}), 400
	
	try:
		# 防止失败后删不掉
		status_info = creation_status.get(container_name)
		if status_info is not None and status_info.get("status") == "failed":
			# clear the recorded failed state and return success
			creation_status.pop(container_name, None)
			return jsonify({
				"success": 1
			}), 200
		
		success = remove_container(container_name)
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e)}), 500
	if success == 0:
		return jsonify({
		"success": 1
		}), 200
	elif success == 1:
		return jsonify({
		"success": 0,
		"error": "container not found",
		"error_reason": "not_found"
		}), 404
	else:
		return jsonify({
		"success": 0,
		"error": "failed to remove container",
		"error_reason": "remove_failed"
		}), 500
	
'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx",
			"user_name":"xxxx",
			"role":['admin'|'collaborator']
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/add_collaborator")
def Add_collaborator():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401
	
	# 提取消息类型和配置
	config = verified_msg.get("config")
	if not config:
		return jsonify({"success": 0, "error": "missing config", "error_reason": "missing_config"}), 400
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name", "error_reason": "missing_container_name"}), 400
	user_name = config.get("user_name")
	if not user_name:
		return jsonify({"success": 0, "error": "missing user_name", "error_reason": "missing_user_name"}), 400
	role_str = config.get("role").lower()
	if role_str not in ('admin', 'collaborator'):
		return jsonify({"success": 0, "error": "invalid role, must be 'admin' or 'collaborator'", "error_reason": "invalid_role"}), 400

	# map string role to ROLE enum
	if role_str == 'admin':
		role_val = ROLE.ADMIN
	else:
		role_val = ROLE.COLLABORATOR

	try:
		success = add_collaborator(container_name, user_name, role_val)
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "internal_error"}), 500
	
	return jsonify({
		"success": success,
		"decrypted_message": verified_msg
	}), 200

'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx"
		}
	},
	signature":"xxxxxx"
}
返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/start_container")
def Start_container_api():
	recived_data = request.get_json(silent=True)
	if not recived_data:
 		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400
	
	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401


	config = verified_msg.get("config") or {}
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"error": "missing container_name", "error_reason": "missing_container_name"}), 400

	# 早返回 表征请求已接受，实际的启动操作在后台线程执行，避免阻塞API响应
	def _bg_start(name: str):
		try:
			mark_start_status(name, 'starting')
			ok = start_container(name)
			if ok:
				mark_start_status(name, 'online')
				# clear tracking after short grace period so subsequent /container_status queries read from docker
				try:
					threading.Timer(5.0, lambda: _clear_action_status(name)).start()
				except Exception:
					pass
			else:
				mark_start_status(name, 'failed', 'start_failed')
		except Exception as e:
			print('bg start error:', e)
			mark_start_status(name, 'failed', str(e))

	try:
		t = threading.Thread(target=_bg_start, args=(container_name,))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "background_thread_failed"}), 500

	return jsonify({"success": 1, "container_status": "starting", "container_name": container_name}), 200
'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx",
			# 虽然设计了timeout参数，但在此不将其控制器下放给用户
		}
	},
	"signature":"xxxxxx"
}
'''
@api_bp.post("/stop_container")
def Stop_container_api():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400


	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401


	config = verified_msg.get("config") or {}
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"error": "missing container_name", "error_reason": "missing_container_name"}), 400

	# spawn background worker to stop container and return early
	def _bg_stop(name: str):
		try:
			mark_stop_status(name, 'stoping')
			ok = stop_container(name)
			if ok:
				mark_stop_status(name, 'offline')
				try:
					threading.Timer(5.0, lambda: _clear_action_status(name)).start()
				except Exception:
					pass
			else:
				mark_stop_status(name, 'failed', 'stop_failed')
		except Exception as e:
			print('bg stop error:', e)
			mark_stop_status(name, 'failed', str(e))

	try:
		t = threading.Thread(target=_bg_stop, args=(container_name,))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "background_thread_failed"}), 500

	return jsonify({"success": 1, "container_status": "stoping", "container_name": container_name}), 200

'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx",
			# 虽然设计了timeout参数，但在此不将其控制器下放给用户
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/restart_container")
def Restart_container_api():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400


	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401


	config = verified_msg.get("config") or {}
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"error": "missing container_name", "error_reason": "missing_container_name"}), 400

	# spawn background worker to restart container and return early
	def _bg_restart(name: str):
		try:
			# On restart we initially treat it as stopping
			mark_restart_status(name, 'stoping')
			ok = restart_container(name)
			if ok:
				mark_restart_status(name, 'online')
				try:
					threading.Timer(5.0, lambda: _clear_action_status(name)).start()
				except Exception:
					pass
			else:
				mark_restart_status(name, 'failed', 'restart_failed')
		except Exception as e:
			print('bg restart error:', e)
			mark_restart_status(name, 'failed', str(e))

	try:
		t = threading.Thread(target=_bg_restart, args=(container_name,))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "background_thread_failed"}), 500

	return jsonify({"success": 1, "container_status": "stoping", "container_name": container_name}), 200


'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx",
			"user_name":"xxxx",
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": [0|1],
}
'''
@api_bp.post("/remove_collaborator")
def Remove_collaborator():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json", "error_reason": "invalid_json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
    
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401
	
	# 提取消息类型和配置
	try:
		config = verified_msg.get("config")
		if not config:
			return jsonify({"success": 0, "error": "missing config", "error_reason": "missing_config"}), 400

		container_name = config.get("container_name")
	except Exception:
		return jsonify({"success": 0, "error": "invalid config format", "error_reason": "invalid_config_format"}), 400
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name", "error_reason": "missing_container_name"}), 400
	user_name = config.get("user_name")
	if not user_name:
		return jsonify({"success": 0, "error": "missing user_name", "error_reason": "missing_user_name"}), 400
	
	try:
		success = remove_collaborator(container_name, user_name)
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "internal_error"}), 500
	
	return jsonify({
		"success": 1,
		"decrypted_message": verified_msg
	}), 200


'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_name":"xxxx",
			"user_name":"xxxx",
			"updated_role":"xxxx"
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
	"success": 0|1,
}
'''
@api_bp.post("/update_role")
def Update_role():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	config = verified_msg.get("config")
	if not config:
		return jsonify({"success": 0, "error": "missing config", "error_reason": "missing_config"}), 400
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name", "error_reason": "missing_container_name"}), 400
	user_name = config.get("user_name")
	if not user_name:
		return jsonify({"success": 0, "error": "missing user_name", "error_reason": "missing_user_name"}), 400
	updated_role_str = config.get("updated_role").lower()
	if updated_role_str not in ('admin', 'collaborator', 'root'):
		return jsonify({"success": 0, "error": "invalid updated_role, must be 'admin', 'collaborator' or 'root'", "error_reason": "invalid_updated_role"}), 400

	# map string role to ROLE enum
	if updated_role_str == 'admin':
		updated_role_val = ROLE.ADMIN
	elif updated_role_str == 'collaborator':
		updated_role_val = ROLE.COLLABORATOR
	else:
		updated_role_val = ROLE.ROOT

	try:
		success = update_role(container_name, user_name, updated_role_val)
	except Exception as e:
		print(e)
		return jsonify({"error": str(e), "error_reason": "internal_error"}), 500
	
	return jsonify({
		"success": success,
		"decrypted_message": verified_msg
	}), 200


def register_blueprints(app):
	app.register_blueprint(api_bp)

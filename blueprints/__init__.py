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

# 状态机（转换态 pending + 空闲态缓存）由 docker_operates/status_cache.py 统一管理，
# 端点只通过 extensions.status_cache 读写（begin_action/finish_action/get_state）。


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
				extensions.status_cache.begin_action(cfg_obj.name, 'create', 'creating')
				create_container(o_name, cfg_obj, public_key=public_key)
				# creation succeeded -> 仅清 pending；端点 miss 后走实时+sshd 检查回填缓存
				extensions.status_cache.finish_action(cfg_obj.name, None)
			except Exception as e:
				# record failure so /container_status can surface it to the controller
				print("create_container error:", e)
				extensions.status_cache.finish_action(cfg_obj.name, 'failed', str(e))


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
		# 状态机统一入口：pending（转换态，返回值等待）优先 → 缓存（空闲态）兜底
		state = extensions.status_cache.get_state(container_name)
		if state["source"] == "pending":
			if state["status"] == "failed":
				return jsonify({"success": 0, "container_status": "failed", "error": "operation failed", "error_reason": state.get("error_reason")}), 200
			return jsonify({"success": 1, "container_status": state["status"], "container_name": container_name}), 200
		if state["source"] == "cache":
			return jsonify({"success": 1, "container_status": state["status"], "container_name": container_name,
							"cache_updated_at": state.get("cache_updated_at")}), 200

		# 缓存 miss：实时查 docker（含 sshd 就绪检查），回填缓存
		container = extensions.docker_client.containers.get(container_name)
		state = None
		try:
			state = container.attrs.get('State', {}).get('Status')
		except Exception:
			state = getattr(container, 'status', None)

		if state is None:
			status_out = "unknown"
		elif state.lower() == 'running':
			# additional readiness checks: ensure sshd is listening (one exec to avoid multiple roundtrips)
			def _exec_check(cmd: str) -> bool:
				try:
					r = container.exec_run(["/bin/sh", "-c", cmd], user="root")
					return getattr(r, 'exit_code', r[0]) == 0
				except Exception:
					return False

			# merge four ssh-detection checks into a single exec_run call
			ssh_listening = _exec_check(
				"ss -ltn 2>/dev/null | grep -q :22 || "
				"netstat -ltn 2>/dev/null | grep -q :22 || "
				"pgrep -f sshd >/dev/null 2>&1 || "
				"ps aux 2>/dev/null | grep -q [s]shd"
			)

			# check authorized_keys exists and is non-empty
			#auth_ok = _exec_check("test -s /root/.ssh/authorized_keys")

			if ssh_listening:
				status_out = "online"
			else:
				# container running but service not yet ready
				status_out = "starting"
		elif state.lower() in ('created', 'restarting', 'starting'):
			status_out = "starting"
		elif state.lower() == 'paused':
			status_out = "paused"
		elif state.lower() in ('exited', 'dead'):
			status_out = "offline"
		else:
			status_out = str(state).lower()

		print(f"Container '{container_name}' status: {status_out}")
		# 实时查询结果回填缓存（后续查询直接吃缓存）
		extensions.status_cache.update(container_name, status_out)

		return jsonify({"success": 1, "container_status": status_out, "container_name": container_name}), 200
	except docker.errors.NotFound:
		return jsonify({"success": 0, "error": "container not found", "error_reason": "not_found", "container_name": container_name}), 404
	except Exception as e:
		return jsonify({"success": 0, "error": str(e), "error_reason": "internal_error"}), 500


@api_bp.post("/container_status_cache")
def Container_status_cache():
	'''
	读容器状态缓存（events 订阅 + 定时对账填充），缓存 miss 时实时查 docker 兜底并回填。
	高频轮询打这个端点，而不是 /container_status（后者含动作追踪与 sshd 就绪检查，较重）。
	'''
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error": "invalid json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed", "error_reason": "invalid_signature"}), 401
	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name", "error_reason": "missing_container_name"}), 400

	cached = extensions.status_cache.get(container_name)
	if cached is not None:
		return jsonify({
			"success": 1,
			"container_status": cached["status"],
			"cache_updated_at": cached["updated_at"],
			"container_name": container_name,
		}), 200

	# 缓存 miss：实时查 docker 状态（简化映射，不做 sshd 检查），回填缓存
	if extensions.docker_client is None:
		try:
			extensions.init_docker()
		except Exception as e:
			return jsonify({"success": 0, "error": f"docker init failed: {e}"}), 500

	try:
		container = extensions.docker_client.containers.get(container_name)
		from ..docker_operates.status_cache import _map_container_to_status
		status_out = _map_container_to_status(container)
		extensions.status_cache.update(container_name, status_out)
		return jsonify({
			"success": 1,
			"container_status": status_out,
			"cache_updated_at": extensions.status_cache.get(container_name)["updated_at"],
			"container_name": container_name,
		}), 200
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
		return jsonify({"success": 0, "error": f"docker init failed: {e}", "error_reason": "docker_init_failed"}), 500

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
		# 防止失败后删不掉：删除成功后清理遗留的 failed 转换态标记
		status_info = extensions.status_cache.get_pending(container_name)
		success = remove_container(container_name)
		if status_info is not None and status_info.get("status") == "failed" and success == 0:
			extensions.status_cache.clear_pending(container_name)
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
			extensions.status_cache.begin_action(name, 'start', 'starting')
			ok = start_container(name)
			if ok:
				# 终态回填缓存（pending 清除后缓存无缝接管）
				extensions.status_cache.finish_action(name, 'online')
			else:
				extensions.status_cache.finish_action(name, 'failed', 'start_failed')
		except Exception as e:
			print('bg start error:', e)
			extensions.status_cache.finish_action(name, 'failed', str(e))

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
			extensions.status_cache.begin_action(name, 'stop', 'stopping')
			ok = stop_container(name)
			if ok:
				# 终态回填缓存（pending 清除后缓存无缝接管）
				extensions.status_cache.finish_action(name, 'offline')
			else:
				extensions.status_cache.finish_action(name, 'failed', 'stop_failed')
		except Exception as e:
			print('bg stop error:', e)
			extensions.status_cache.finish_action(name, 'failed', str(e))

	try:
		t = threading.Thread(target=_bg_stop, args=(container_name,))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "background_thread_failed"}), 500

	return jsonify({"success": 1, "container_status": "stopping", "container_name": container_name}), 200

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
			extensions.status_cache.begin_action(name, 'restart', 'restarting')
			ok = restart_container(name)
			if ok:
				# 终态回填缓存（pending 清除后缓存无缝接管）
				extensions.status_cache.finish_action(name, 'online')
			else:
				extensions.status_cache.finish_action(name, 'failed', 'restart_failed')
		except Exception as e:
			print('bg restart error:', e)
			extensions.status_cache.finish_action(name, 'failed', str(e))

	try:
		t = threading.Thread(target=_bg_restart, args=(container_name,))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e), "error_reason": "background_thread_failed"}), 500

	return jsonify({"success": 1, "container_status": "stopping", "container_name": container_name}), 200


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
    "machine_disk": { "total_gb": ..., "used_gb": ..., "free_gb": ..., "percent": ... },
    "container": { "overlay_rw_bytes": ..., "bind_mount_bytes": ..., "bind_mount_path": ..., "total_bytes": ... }
}
'''
@api_bp.post("/check_disk_usage")
def Check_disk_usage():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error": "invalid json", "error_reason": "invalid_json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed",
						"error_reason": "invalid_signature"}), 401

	config = verified_msg.get("config") or {}
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name",
						"error_reason": "missing_container_name"}), 400

	try:
		if extensions.docker_client is None:
			extensions.init_docker()
	except Exception as e:
		return jsonify({"success": 0, "error": f"docker init failed: {e}",
						"error_reason": "docker_init_failed"}), 500

	from ..services.container_service import get_disk_usage
	try:
		result = get_disk_usage(container_name)
	except Exception as e:
		return jsonify({"success": 0, "error": str(e),
						"error_reason": "internal_error"}), 500

	return jsonify({"success": 1, **result}), 200


'''
通信数据格式：
发送格式：
{
    "message":{
        "config":
        {
            "container_name":"xxxx",
            "action":"pause"|"unpause"
        }
    },
    "signature":"xxxxxx"
}
返回格式：
{
    "success": [0|1]
}
'''
@api_bp.post("/pause_container")
def Pause_container():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error": "invalid json", "error_reason": "invalid_json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed",
						"error_reason": "invalid_signature"}), 401

	config = verified_msg.get("config") or {}
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name",
						"error_reason": "missing_container_name"}), 400

	action = config.get("action", "pause")
	if action not in ("pause", "unpause"):
		return jsonify({"success": 0, "error": "invalid action, must be 'pause' or 'unpause'",
						"error_reason": "invalid_action"}), 400

	try:
		if extensions.docker_client is None:
			extensions.init_docker()
	except Exception as e:
		return jsonify({"success": 0, "error": f"docker init failed: {e}",
						"error_reason": "docker_init_failed"}), 500

	try:
		container = extensions.docker_client.containers.get(container_name)
		if action == "pause":
			container.pause()
			print(f"Container {container_name} paused.")
		else:
			container.unpause()
			print(f"Container {container_name} unpaused.")
	except docker.errors.NotFound:
		return jsonify({"success": 0, "error": "container not found",
						"error_reason": "not_found"}), 404
	except Exception as e:
		return jsonify({"success": 0, "error": str(e),
						"error_reason": "internal_error"}), 500

	return jsonify({"success": 1}), 200


@api_bp.post("/clean_mount")
def Clean_mount():
	"""清理已删除容器的宿主机 mount 目录。

	安全检查：路径必须以 /home/ 开头且包含 /containers/。
	"""
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"success": 0, "error": "invalid json", "error_reason": "invalid_json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed",
						"error_reason": "invalid_signature"}), 401

	config = verified_msg.get("config") or {}
	mount_path = config.get("mount_path")
	if not mount_path:
		return jsonify({"success": 0, "error": "missing mount_path",
						"error_reason": "missing_mount_path"}), 400

	# 安全检查：路径必须在 /home/*/containers/ 下
	if not str(mount_path).startswith("/home/") or "/containers/" not in str(mount_path):
		return jsonify({"success": 0, "error": "invalid mount_path",
						"error_reason": "invalid_path"}), 400

	import subprocess
	try:
		subprocess.run(["rm", "-rf", str(mount_path)], timeout=30, check=False)
		print(f"Mount cleaned: {mount_path}")
		return jsonify({"success": 1}), 200
	except subprocess.TimeoutExpired:
		return jsonify({"success": 0, "error": "rm timeout",
						"error_reason": "timeout"}), 500
	except Exception as e:
		return jsonify({"success": 0, "error": str(e),
						"error_reason": "internal_error"}), 500


def register_blueprints(app):
	app.register_blueprint(api_bp)

from flask import Blueprint, jsonify, request
from ..utils.CheckKeys import get_verified_msg
from ..utils.Container import Container
from ..services.container_service import (
    create_container,
    remove_container,
    add_collaborator,
    remove_collaborator,
    update_role
)
import threading
from .. import extensions
from ..constant import ROLE
import docker

# debug
# success = 1

api_bp = Blueprint("api", __name__, url_prefix="/api")

'''
通信数据格式：
发送格式：
{
	"message":{
		"owner_name":"xxxx",
		"config":
		{
			"gpu_list":[0,1,2,...],
			"cpu_number":20,
			"memory":16,#GB
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
		return jsonify({"error":"invalid json"}), 400
    

	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
    
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
    
	# 提取消息配置
	owner_name = verified_msg.get("owner_name")
	config = verified_msg.get("config")
	public_key = verified_msg.get("public_key", None)
    
	try:
		cfg = Container.Config_info(**config)
	except Exception as e:
		return jsonify({"error": f"invalid config: {e}"}), 400
	# ensure docker client so we can pre-check container name collisions
	if extensions.docker_client is None:
		try:
			extensions.init_docker()
		except Exception as e:
			return jsonify({"error": f"docker init failed: {e}"}), 500

	# 额外预检：检查是否已存在同名容器，避免创建后才发现冲突
	try:
		existing = None
		try:
			existing = extensions.docker_client.containers.get(cfg.name)
		except docker.errors.NotFound:
			existing = None
		if existing is not None:
			return jsonify({"success": 0, "error": f"container {cfg.name} already exists", "container_name": cfg.name}), 409
	except Exception as e:
		# if we can't contact docker, return an error
		return jsonify({"success": 0, "error": f"docker check failed: {e}"}), 500
	# spawn background thread to perform actual creation and return early
	def _bg_create(o_name, cfg_obj):
		try:
			create_container(o_name, cfg_obj, public_key=public_key)
		except Exception as e:
			# cannot use Flask response helpers from a background thread (no app context)
			# Log the error so operators can diagnose; if async error reporting is required,
			# implement an out-of-band status/notification mechanism.
			print("create_container error:", e)


	try:
		t = threading.Thread(target=_bg_create, args=(owner_name, cfg))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e)}), 500


	print("SUCCESS")
    
	return jsonify({
		"success": 1,
		"container_status": "creating",
		"container_name": cfg.name
	}), 200


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
		return jsonify({"success": 0, "error": "invalid_signature or decryption failed"}), 401
	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name"}), 400

	# ensure docker client
	if extensions.docker_client is None:
		try:
			extensions.init_docker()
		except Exception as e:
			return jsonify({"success": 0, "error": f"docker init failed: {e}"}), 500

	try:
		# docker SDK allows get by name
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

		return jsonify({"success": 1, "container_status": status_out, "container_name": container_name}), 200
	except docker.errors.NotFound:
		return jsonify({"success": 0, "error": "container not found", "container_name": container_name}), 404
	except Exception as e:
		return jsonify({"success": 0, "error": str(e)}), 500

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
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置（防御性处理：可能没有 config）
	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"error": "missing container_name"}), 400
	
	try:
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
		"error": "container not found"
		}), 404
	else:
		return jsonify({
		"success": 0,
		"error": "failed to remove container"
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
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	config = verified_msg.get("config")
	
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name"}), 400
	user_name = config.get("user_name")
	if not user_name:
		return jsonify({"success": 0, "error": "missing user_name"}), 400
	role_str = config.get("role").lower()
	if role_str not in ('admin', 'collaborator'):
		return jsonify({"success": 0, "error": "invalid role, must be 'admin' or 'collaborator'"}), 400

	# map string role to ROLE enum
	if role_str == 'admin':
		role_val = ROLE.ADMIN
	else:
		role_val = ROLE.COLLABORATOR

	try:
		success = add_collaborator(container_name, user_name, role_val)
	except Exception as e:
		print(e)
		return jsonify({"success": 1, "error": str(e)}), 500
	
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
		return jsonify({"error":"invalid json"}), 400
	
	# 使用 get_verified_msg 函数解密并验证
	verified_msg = get_verified_msg(recived_data)
	
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401
	
	# 提取消息类型和配置
	try:
		config = verified_msg.get("config")
	
		container_name = config.get("container_name")
	except Exception:
		return jsonify({"success": 0, "error": "invalid config format"}), 400
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name"}), 400
	user_name = config.get("user_name")
	if not user_name:
		return jsonify({"success": 0, "error": "missing user_name"}), 400
	
	try:
		success = remove_collaborator(container_name, user_name)
	except Exception as e:
		print(e)
		return jsonify({"success": 0, "error": str(e)}), 500
	
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
	container_name = config.get("container_name")
	if not container_name:
		return jsonify({"success": 0, "error": "missing container_name"}), 400
	user_name = config.get("user_name")
	if not user_name:
		return jsonify({"success": 0, "error": "missing user_name"}), 400
	updated_role_str = config.get("updated_role").lower()
	if updated_role_str not in ('admin', 'collaborator', 'root'):
		return jsonify({"success": 0, "error": "invalid updated_role, must be 'admin', 'collaborator' or 'root'"}), 400

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
		return jsonify({"error": str(e)}), 500
	
	return jsonify({
		"success": success,
		"decrypted_message": verified_msg
	}), 200


def register_blueprints(app):
	app.register_blueprint(api_bp)


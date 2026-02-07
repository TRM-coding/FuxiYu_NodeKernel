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
import docker

# debug
# success = 1

api_bp = Blueprint("api", __name__, url_prefix="/api")

'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"gpu_list":[0,1,2,...],
			"cpu_number":20,
			"memory":16,#GB
			"user_name":'example',
			"port":0,
			"image":"ubuntu24.04"
		}
	},
	"signature":"xxxxxx"
}
返回格式：
{
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
	
	try:
		cfg = Container.Config_info(**config)
	except Exception as e:
		return jsonify({"error": f"invalid config: {e}"}), 400

	# spawn background thread to perform actual creation and return early
	def _bg_create(o_name, cfg_obj):
		try:
			create_container(o_name, cfg_obj)
		except Exception as e:
			print("background create_container error:", e)

	try:
		t = threading.Thread(target=_bg_create, args=(owner_name, cfg))
		t.daemon = True
		t.start()
	except Exception as e:
		print(e)
		return jsonify({"error": str(e)}), 500


	print("SUCCESS")
	
	return jsonify({
		"container_status": "CREATING",
		"container_name": cfg.name
	}), 200


@api_bp.post("/container_status")
def Container_status():
	recived_data = request.get_json(silent=True)
	if not recived_data:
		return jsonify({"error":"invalid json"}), 400

	verified_msg = get_verified_msg(recived_data)
	if not verified_msg:
		return jsonify({"error": "invalid_signature or decryption failed"}), 401

	config = verified_msg.get("config") or {}
	container_name = config.get("container_name") or config.get("name")
	if not container_name:
		return jsonify({"error": "missing container_name"}), 400

	# ensure docker client
	if extensions.docker_client is None:
		try:
			extensions.init_docker()
		except Exception as e:
			return jsonify({"error": f"docker init failed: {e}"}), 500

	try:
		# docker SDK allows get by name
		container = extensions.docker_client.containers.get(container_name)
		state = None
		try:
			state = container.attrs.get('State', {}).get('Status')
		except Exception:
			state = getattr(container, 'status', None)

		if state is None:
			status_out = "UNKNOWN"
		elif state.lower() == 'running':
			status_out = "RUNNING"
		elif state.lower() in ('created', 'restarting', 'starting'):
			status_out = "STARTING"
		elif state.lower() in ('exited', 'dead'):
			status_out = "STOPPED"
		else:
			status_out = state.upper()

		return jsonify({"container_status": status_out, "container_name": container_name}), 200
	except docker.errors.NotFound:
		# not created yet
		return jsonify({"container_status": "CREATING", "container_name": container_name}), 200
	except Exception as e:
		return jsonify({"error": str(e)}), 500

'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_id":"xxxx"
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
	
	# 提取消息类型和配置
	config = verified_msg.get("config")
	
	
	
	try:
		success = remove_container(**config)
	except Exception as e:
		print(e)
		return jsonify({"error": str(e)}), 500
	
	return jsonify({
		"success": success
	}), 200
	
'''
通信数据格式：
发送格式：
{
	"message":{
		"config":
		{
			"container_id":"xxxx",
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
	
	
	
	try:
		success = add_collaborator(**config)
	except Exception as e:
		print(e)
		return jsonify({"error": str(e)}), 500
	
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
			"container_id":"xxxx",
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
	config = verified_msg.get("config")
	
	
	try:
		success = remove_collaborator(**config)
	except Exception as e:
		print(e)
		return jsonify({"error": str(e)}), 500
	
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
			"container_id":"xxxx",
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
	
	try:
		success = update_role(**config)
	except Exception as e:
		print(e)
		return jsonify({"error": str(e)}), 500
	
	return jsonify({
		"success": success,
		"decrypted_message": verified_msg
	}), 200


def register_blueprints(app):
	app.register_blueprint(api_bp)


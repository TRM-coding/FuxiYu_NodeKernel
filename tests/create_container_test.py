#TODO: 完成测试用例编写
import sys
import os

import pytest
import docker
from FuxiYu_NodeKernel.services.container_service import (
    create_container,
    CreateContainerReturn,
)
from FuxiYu_NodeKernel.utils.Container import Container

# 全局/docker客户端初始化（确保与被测函数使用的docker_client一致）
docker_client = docker.from_env()

def test_happy_path():
    """测试create_container函数的正常流程（真实Docker环境，Happy Path）"""
    # ========== 步骤1：构造合法的测试输入（Config_info实例，user_name=admin） ==========
    test_config = Container.Config_info(
        gpu_list=[],  # 简化测试，无GPU依赖（如需测试GPU，确保Docker环境支持nvidia-docker）
        cpu_number=2,  # 合理CPU核数（避免资源占用过高）
        memory=4,      # 合理内存大小（4GB，满足容器运行需求）
        user_name="admin",  # 要求的admin用户名
        port=2233,     # 合法端口（1024-49151之间，避免端口冲突）
        image="ubuntu:20.04"  # 稳定可用的Ubuntu镜像（确保Docker已拉取或能自动拉取）
    )
    
    # 前置清理：避免端口冲突或同名容器残留（提高测试可重复性）
    for container in docker_client.containers.list(all=True):
        if str(test_config.port) in container.name or "admin_" in container.name:
            container.stop() if container.status == "running" else None
            container.remove(force=True)
    
    try:
        # ========== 步骤2：调用待测试的create_container函数（真实执行） ==========
        result = create_container(test_config)
        
        # ========== 步骤3：断言返回值的正确性 ==========
        # 3.1 断言返回值类型和核心属性
        assert isinstance(result, CreateContainerReturn), "返回值不是预期的CreateContainerReturn实例"
        assert len(result.container_id) > 0, "返回的容器ID为空"
        assert result.container_name.startswith("admin_"), "容器名称未以admin_开头"
        assert result.container_id[:12] in result.container_name
        
        # ========== 步骤4：验证真实Docker容器的状态和属性 ==========
        # 4.1 根据返回的容器ID获取真实容器对象
        real_container = docker_client.containers.get(result.container_id)
        
        # 4.2 断言容器的基本状态
        assert real_container.status == "running", "容器未处于运行状态"
        assert real_container.name == result.container_name, "容器名称与返回结果不一致"
        
        # 4.3 断言容器的配置参数（与测试输入一致）
        # 验证内存限制（转换单位匹配Docker的返回格式）
        expected_mem_limit = test_config.memory * 1024 * 1024 * 1024  # GB -> 字节
        assert real_container.attrs["HostConfig"]["Memory"] == expected_mem_limit, "容器内存限制配置错误"
        
        # 验证CPU配额
        expected_cpu_quota = test_config.cpu_number * 100000
        assert real_container.attrs["HostConfig"]["CpuQuota"] == expected_cpu_quota, "容器CPU配额配置错误"
        
        # 验证端口映射（22/tcp 映射到指定端口）
        port_bindings = real_container.attrs["HostConfig"]["PortBindings"]
        assert "22/tcp" in port_bindings, "容器未配置22端口映射"
        assert port_bindings["22/tcp"][0]["HostPort"] == str(test_config.port), "端口映射配置错误"
        
        # 4.4 验证SSH服务是否正常配置（可选，进一步验证业务逻辑）
        # 执行命令检查sshd进程是否运行
        # 1) 确认 sshd 可执行文件存在（说明 openssh-server 已安装）
        exec_result = real_container.exec_run(["/bin/sh", "-c", "test -x /usr/sbin/sshd"], user="root")
        assert exec_result.exit_code == 0, "sshd 不存在或不可执行（openssh-server 可能安装失败）"

        # 2) 确认容器内 22 端口在监听（0016 是 22 的十六进制）
        exec_result = real_container.exec_run(
    ["/bin/sh", "-c", r"cat /proc/net/tcp | awk 'NR>1{print $2}' | cut -d: -f2 | grep -qi '^0016$'"],
    user="root",
)
        assert exec_result.exit_code == 0, "容器内 22 端口未监听，可能 sshd 未启动"
        
    finally:
        # ========== 步骤5：测试后置清理（避免残留资源） ==========
        # 停止并删除测试创建的容器，保持环境干净
        try:
            real_container = docker_client.containers.get(result.container_id)
            real_container.stop()
            real_container.remove(force=True)
        except:
            pass

def test_error_path_invalid_config():
    raise NotImplementedError

def test_error_path_container_exist():
    raise NotImplementedError


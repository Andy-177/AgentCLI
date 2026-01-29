import json
import os
import requests
import subprocess
import re
import platform
import datetime  # 保留基础datetime模块
from pydantic import BaseModel
import sys
import io
import contextlib

# 定义配置模型
class Config(BaseModel):
    api_url: str = "https://api.example.com/v1/chat/completions"
    api_key: str = "your_api_key_here"
    model: str = "default_model"
    user_name: str = "用户"
    ai_name: str = "AI"
    prompt: str = "None"  # 原prompt_file改为prompt
    send_history: bool = False
    logger: str = "None"  # 可选值：all/format/lite/None

    def save_to_file(self, file_path="config.json"):
        """保存配置文件"""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=4, ensure_ascii=False)

    @classmethod
    def load_and_validate(cls, file_path="config.json"):
        """
        加载并校验配置文件，仅修复不合法的配置项
        :return: (配置实例, 错误信息列表)
        """
        config_errors = []  # 记录配置错误信息
        default_config = cls()
        default_dict = default_config.model_dump()
        loaded_data = {}

        # 1. 文件不存在：创建默认配置
        if not os.path.exists(file_path):
            default_config.save_to_file(file_path)
            return default_config, []

        # 2. 文件存在：尝试读取文件（处理JSON格式错误）
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
            if not isinstance(loaded_data, dict):
                raise ValueError("配置文件内容不是有效的JSON对象")
        except json.JSONDecodeError as e:
            # JSON格式错误：备份文件 + 生成默认配置
            error_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"config_error_backup_{error_time}.json"
            with open(file_path, "rb") as f_src, open(backup_path, "wb") as f_dst:
                f_dst.write(f_src.read())
            
            config_errors.append({
                "type": "file_error",
                "message": f"配置文件JSON格式错误：{str(e)}",
                "backup_file": backup_path,
                "action": "已生成默认配置文件，原错误文件已备份为"
            })
            default_config.save_to_file(file_path)
            return default_config, config_errors
        except Exception as e:
            # 其他读取错误
            config_errors.append({
                "type": "file_error",
                "message": f"读取配置文件失败：{str(e)}",
                "action": "已使用默认配置"
            })
            return default_config, config_errors

        # 3. 逐个校验配置项（仅修复不合法项）
        validated_data = {}
        for key, default_value in default_dict.items():
            # 获取用户配置值（不存在则用默认值）
            user_value = loaded_data.get(key, default_value)
            
            # 兼容旧的prompt_file配置项（自动迁移）
            if key == "prompt" and "prompt_file" in loaded_data and key not in loaded_data:
                user_value = loaded_data["prompt_file"]
                config_errors.append({
                    "type": "config_migrate",
                    "message": "检测到旧配置项prompt_file，已自动迁移为新配置项prompt",
                    "original_key": "prompt_file",
                    "new_key": "prompt",
                    "value": user_value
                })
            
            # 校验并修复配置项
            if key == "logger":
                # 校验logger取值范围（包含lite选项）
                valid_logger_values = ["all", "format", "lite", "None"]
                if user_value not in valid_logger_values:
                    config_errors.append({
                        "item": key,
                        "original_value": user_value,
                        "error_reason": f"取值不在允许范围内（{', '.join(valid_logger_values)}）",
                        "fixed_value": default_value
                    })
                    validated_data[key] = default_value
                else:
                    validated_data[key] = user_value
            
            elif key == "send_history":
                # 校验布尔类型配置
                if not isinstance(user_value, bool):
                    config_errors.append({
                        "item": key,
                        "original_value": user_value,
                        "error_reason": "类型错误，必须是布尔值（True/False）",
                        "fixed_value": default_value
                    })
                    validated_data[key] = default_value
                else:
                    validated_data[key] = user_value
            
            elif key in ["api_url", "api_key", "model", "user_name", "ai_name", "prompt"]:  # 改为prompt
                # 校验字符串类型配置
                if not isinstance(user_value, str):
                    config_errors.append({
                        "item": key,
                        "original_value": user_value,
                        "error_reason": "类型错误，必须是字符串",
                        "fixed_value": default_value
                    })
                    validated_data[key] = default_value
                else:
                    validated_data[key] = user_value
            
            else:
                # 未知配置项：使用默认值
                validated_data[key] = default_value

        # 步骤4：保存修复后的配置（仅当有错误时）
        if config_errors and any(err.get("item") for err in config_errors):
            try:
                fixed_config = cls(**validated_data)
                fixed_config.save_to_file(file_path)
            except Exception as e:
                config_errors.append({
                    "type": "save_error",
                    "message": f"保存修复后的配置失败：{str(e)}"
                })
                return default_config, config_errors

        # 步骤5：返回修复后的配置和错误信息
        return cls(**validated_data), config_errors

# ===================== 工具函数 =====================
def format_json_for_log(json_data, prefix="[日志] "):
    """格式化JSON数据用于日志输出"""
    if isinstance(json_data, str):
        json_data = json.loads(json_data)
    
    if isinstance(json_data, dict):
        lines = []
        for key, value in json_data.items():
            if isinstance(value, dict):
                value_str = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
                lines.append(f'"{key}":{value_str}')
            else:
                value_str = json.dumps(value, ensure_ascii=False)
                lines.append(f'"{key}":{value_str}')
        
        formatted_lines = [f"{prefix}{line}" for line in lines]
        return "\n".join(formatted_lines)
    return f"{prefix}{json.dumps(json_data, ensure_ascii=False, separators=(',', ':'))}"

# ===================== Agent类（包含MCP处理逻辑） =====================
class Agent:
    def __init__(self):
        """初始化Agent，加载并校验配置"""
        # 自动检测并创建prompt文件夹
        self.prompt_dir = "prompt"
        self.create_prompt_dir()
        
        # 加载配置并获取错误信息
        self.config, self.config_errors = Config.load_and_validate()
        self.prompt_files = self.get_prompt_files()
        self.chat_history = []
        
        # 打印配置错误提示（如果有）
        self.print_config_errors()

    def create_prompt_dir(self):
        """检测并创建prompt文件夹"""
        if not os.path.exists(self.prompt_dir):
            try:
                os.makedirs(self.prompt_dir)
                print(f"📁 已自动创建prompt文件夹：{os.path.abspath(self.prompt_dir)}")
            except Exception as e:
                print(f"⚠️ 创建prompt文件夹失败：{str(e)}")
        else:
            print(f"📁 prompt文件夹已存在：{os.path.abspath(self.prompt_dir)}")

    def print_config_errors(self):
        """打印配置错误修复信息"""
        if not self.config_errors:
            return
        
        print("\n⚠️  检测到配置文件存在问题，已自动修复：")
        print("-" * 60)
        
        for error in self.config_errors:
            if error.get("type") == "file_error":
                # 文件级错误
                print(f"📁 {error['message']}")
                if "backup_file" in error:
                    print(f"   {error['action']} {error['backup_file']}")
                else:
                    print(f"   {error['action']}")
            elif error.get("type") == "config_migrate":
                # 配置项迁移提示
                print(f"🔄 {error['message']}")
                print(f"   原配置项值：{repr(error['value'])}")
            elif error.get("item"):
                # 配置项级错误
                print(f"🔧 配置项 '{error['item']}'：")
                print(f"   原始值: {repr(error['original_value'])}")
                print(f"   错误原因: {error['error_reason']}")
                print(f"   修复后值: {repr(error['fixed_value'])}")
            elif error.get("type") == "save_error":
                # 保存错误
                print(f"❌ {error['message']}")
        
        print("-" * 60)
        print("💡 你可以使用 ;;config 命令重新配置这些项\n")

    def get_prompt_files(self):
        """获取prompt文件夹下的所有 .txt 文件"""
        if not os.path.exists(self.prompt_dir):
            return ["无"]
        
        files = [f for f in os.listdir(self.prompt_dir) if f.endswith('.txt')]
        return ["无"] + files

    def save_config(self):
        """保存配置（仅当通过config命令设置合法值时）"""
        self.config.save_to_file()
        print("✅ 配置已保存！")
    
    def log_ai_message(self, message):
        """统一的AI日志打印函数"""
        logger_mode = self.config.logger
        # lite模式下不打印AI消息日志
        if logger_mode in ["all", "format"]:
            if isinstance(message, str) and message.startswith(";;") and message.endswith(";;"):
                json_str = message[2:-2]
                try:
                    json_data = json.loads(json_str)
                    if logger_mode == "all":
                        print(f"[日志] {self.config.ai_name}: {json.dumps(json_data, ensure_ascii=False, separators=(',', ':'))}")
                    elif logger_mode == "format":
                        print(f"[日志] {self.config.ai_name}:")
                        print(format_json_for_log(json_data, "  "))
                except json.JSONDecodeError:
                    print(f"[日志] {self.config.ai_name}: {message}")
            else:
                print(f"[日志] {self.config.ai_name}: {message}")

    def send_message(self, user_message):
        """发送用户消息"""
        if not user_message:
            return
        self.call_api(user_message)

    def call_api(self, user_message):
        """调用API获取AI响应"""
        try:
            system_content = f"你是一个名为{self.config.ai_name}的AI助手，正在与用户{self.config.user_name}对话。"
            system_content += f"\n当前系统类型是：{platform.system()}"
            system_content += "\n你只能使用MCP协议格式进行操作，格式如下："
            system_content += "\n1. 执行终端命令："
            system_content += "\n;;{\"mcp\":\"request\",\"method\":\"system.terminal.run\",\"params\":{\"command\":\"echo hello\"}};;"
            system_content += "\n2. 执行Python代码："
            system_content += "\n- 单行命令：;;{\"mcp\":\"request\",\"method\":\"python.run.execute\",\"params\":{\"command\":\"print('hello')\"}};;"
            system_content += "\n- 多行脚本：;;{\"mcp\":\"request\",\"method\":\"python.run.execute\",\"params\":{\"script\":[\"print('hello')\",\"print('world')\",\"x=1+1\",\"print(x)\"]}};;"
            system_content += "\n3. 获取时间：;;{\"mcp\":\"request\",\"method\":\"system.time.get\",\"params\":{\"type\":\"date | time | all | stamp\"}};;"
            system_content += "\n4. 获取系统信息：;;{\"mcp\":\"request\",\"method\":\"system.info.get\",\"params\":{}};;"
            system_content += "\n注意：收到MCP响应后，不需要再次生成MCP请求，直接用自然语言回复用户即可"

            # 加载prompt文件夹中的提示词文件
            if self.config.prompt != "None":
                prompt_file_path = os.path.join(self.prompt_dir, self.config.prompt)
                try:
                    with open(prompt_file_path, "r", encoding="utf-8") as f:
                        prompt_content = f.read()
                    system_content += f"\n{prompt_content}"
                except FileNotFoundError:
                    self.log_ai_message(f"提示词文件不存在: {prompt_file_path}")
                except Exception as e:
                    self.log_ai_message(f"读取提示词文件失败: {str(e)}")

            messages = [{"role": "system", "content": system_content}]

            if self.config.send_history:
                for entry in self.chat_history:
                    messages.append({"role": entry["role"], "content": entry["content"]})

            messages.append({"role": "user", "content": user_message})

            response = requests.post(
                self.config.api_url,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={"model": self.config.model, "messages": messages}
            )

            if response.status_code == 200:
                ai_response = response.json().get("choices", [{}])[0].get("message", {}).get("content", "未获取到回复")
                self.handle_ai_response(ai_response, user_message)
            else:
                self.log_ai_message(f"错误: {response.text}")
        except Exception as e:
            self.log_ai_message(f"请求失败: {str(e)}")

    def handle_ai_response(self, ai_response, user_message):
        """处理AI响应"""
        mcp_pattern = r";;({.*?});;"
        mcp_matches = re.findall(mcp_pattern, ai_response, re.DOTALL)
        
        if mcp_matches:
            for mcp_str in mcp_matches:
                try:
                    mcp_json = json.loads(mcp_str)
                    if mcp_json.get("mcp") == "request":
                        # 直接调用自身的MCP处理方法
                        mcp_response = self.handle_mcp_request(mcp_json)
                        self.chat_history.append({"role": "assistant", "content": ai_response})
                        self.call_api(mcp_response)
                except json.JSONDecodeError as e:
                    error_msg = f"MCP JSON解析错误: {str(e)}"
                    self.log_ai_message(error_msg)
                except Exception as e:
                    error_msg = f"MCP处理错误: {str(e)}"
                    self.log_ai_message(error_msg)
        else:
            print(f"{self.config.ai_name}: {ai_response}")
            self.chat_history.append({"role": "user", "content": user_message})
            self.chat_history.append({"role": "assistant", "content": ai_response})

    # ===================== 新增：统一的info构造函数 =====================
    def build_info_dict(self, parsed):
        """
        统一构造info字典
        :param parsed: parse_mcp_request解析后的字典
        :return: 标准化的info字典
        """
        return {
            "method": parsed["full_method"],  # 完整三级方法名
            "params": parsed["params"]        # 请求参数
        }

    # ===================== 新增：统一的响应处理函数 =====================
    def handle_mcp_response(self, parsed, is_success=True, result=None, error_code=None, error_msg=None):
        """
        统一处理MCP响应生成
        :param parsed: parse_mcp_request解析后的字典
        :param is_success: 是否成功（True/False）
        :param result: 成功时的结果数据（dict）
        :param error_code: 失败时的错误码（int）
        :param error_msg: 失败时的错误信息（str）
        :return: 格式化的MCP响应字符串
        """
        # 统一构造info字典
        info = self.build_info_dict(parsed)
        
        # 根据成功/失败生成响应
        if is_success:
            response = {
                "mcp": "response",
                "info": info,
                "result": result or {}
            }
        else:
            response = {
                "mcp": "response",
                "info": info,
                "error": {
                    "code": error_code or 9999,
                    "message": error_msg or "未知错误"
                }
            }
        
        # 生成最终响应字符串
        response_str = f";;{json.dumps(response, ensure_ascii=False, separators=(',', ':'))};;"
        
        # 统一打印响应日志（根据logger模式）
        self.log_mcp_response(response_str)
        
        return response_str

    def log_mcp_response(self, response_str):
        """统一打印MCP响应日志"""
        logger_mode = self.config.logger
        if logger_mode in ["all", "format"]:
            try:
                json_str = response_str[2:-2]
                json_data = json.loads(json_str)
                if logger_mode == "all":
                    print(f"[日志] mcp返回:\n{json.dumps(json_data, ensure_ascii=False, separators=(',', ':'))}")
                elif logger_mode == "format":
                    print(f"[日志] mcp返回:")
                    print(format_json_for_log(json_data, "  "))
            except:
                print(f"[日志] mcp返回: {response_str}")

    # ===================== 核心改造：统一MCP协议解析函数 =====================
    def parse_mcp_protocol(self, mcp_json):
        """
        统一解析MCP协议请求，实现协议解析与业务处理解耦
        负责：格式合法性校验、核心字段提取、三级method解析
        :param mcp_json: 原始MCP请求JSON字典
        :return: 标准化解析结果（dict），包含error则为解析失败
        """
        try:
            # 1. 基础格式校验：必须包含mcp和method字段
            if not isinstance(mcp_json, dict):
                return {"error": "MCP请求必须是JSON对象", "error_code": 1000}
            
            if "mcp" not in mcp_json:
                return {"error": "MCP请求缺少核心字段：mcp", "error_code": 1001}
            
            if mcp_json["mcp"] != "request":
                return {"error": f"不支持的MCP类型：{mcp_json['mcp']}，仅支持request", "error_code": 1002}
            
            if "method" not in mcp_json:
                return {"error": "MCP请求缺少核心字段：method", "error_code": 1003}
            
            full_method = mcp_json["method"]
            if not isinstance(full_method, str) or not full_method.strip():
                return {"error": "method字段必须是非空字符串", "error_code": 1004}
            
            # 2. 三级method解析（module.method.func）
            method_parts = full_method.strip().split(".")
            if len(method_parts) != 3:
                return {"error": f"method必须是三级格式：module.method.func，当前：{full_method}", "error_code": 1005}
            
            module, method, func = method_parts
            if not all([module.strip(), method.strip(), func.strip()]):
                return {"error": "三级method的每一部分都不能为空", "error_code": 1006}
            
            # 3. 提取参数（params可选，默认空字典）
            params = mcp_json.get("params", {})
            if not isinstance(params, dict):
                return {"error": "params字段必须是JSON对象", "error_code": 1007}
            
            # 4. 返回标准化解析结果（无error表示解析成功）
            return {
                "mcp_type": mcp_json["mcp"],       # MCP类型（固定为request）
                "module": module,                 # 一级模块（如system/python）
                "method": method,                 # 二级方法（如terminal/run）
                "func": func,                     # 三级函数（如run/execute）
                "full_method": full_method,       # 完整三级method
                "params": params,                 # 标准化参数字典
                "raw_request": mcp_json           # 保留原始请求（可选，用于日志/调试）
            }
        
        except Exception as e:
            return {"error": f"MCP协议解析异常：{str(e)}", "error_code": 9999}

    # ===================== MCP协议处理方法（改造后） =====================
    def handle_mcp_request(self, mcp_json):
        """处理MCP请求并返回响应（改造后：仅负责调度，不做解析）"""
        logger_mode = self.config.logger
        # lite模式下不打印MCP请求的原始日志
        if logger_mode in ["all", "format"]:
            if logger_mode == "all":
                print(f"[日志] mcp请求:\n{json.dumps(mcp_json, ensure_ascii=False, separators=(',', ':'))}")
            elif logger_mode == "format":
                print(f"[日志] mcp请求:")
                print(format_json_for_log(mcp_json, "  "))
        
        # 核心：调用统一解析层解析MCP协议
        parsed = self.parse_mcp_protocol(mcp_json)
        
        # 解析失败：返回标准化错误响应
        if "error" in parsed:
            return self.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=parsed.get("error_code", 1001),
                error_msg=parsed["error"]
            )
        
        # 解析成功：根据模块调度业务处理
        module = parsed["module"]
        if module == "system":
            return self.handle_system_module(parsed)
        elif module == "python":
            return self.handle_python_module(parsed)
        else:
            # 未知模块：返回标准化错误响应
            return self.handle_mcp_response(
                parsed=parsed,
                is_success=False,
                error_code=1002,
                error_msg=f"未知模块: {module}，仅支持system/python"
            )
    
    def handle_system_module(self, parsed):
        """处理system模块的MCP请求（改造后：仅接收统一解析后的标准化数据）"""
        try:
            # 直接从统一解析结果中获取数据，无需再解析
            full_method = parsed["full_method"]
            params = parsed["params"]
            result = {}
            
            # system模块支持的方法：terminal.run, time.get, info.get
            if parsed["method"] == "terminal" and parsed["func"] == "run":
                # 修改：只处理command键名，不再遍历所有key
                if "command" in params:
                    cmd_value = params["command"]
                    if cmd_value.strip():
                        output, error = self.run_terminal_command(cmd_value)
                        if error:
                            result["command"] = f"错误: {error}"
                        elif output:
                            result["command"] = output.strip()
                        else:
                            result["command"] = "命令执行成功（无输出）"
                    else:
                        result["command"] = "错误: 命令内容不能为空"
                else:
                    # 没有command键的错误提示
                    result["error"] = "参数错误：必须提供'command'键来指定要执行的终端命令"
                # 使用统一响应函数生成成功响应
                return self.handle_mcp_response(
                    parsed=parsed,
                    is_success=True,
                    result=result
                )
            
            elif parsed["method"] == "time" and parsed["func"] == "get":
                time_type = list(params.values())[0] if params else ""
                time_value = self.get_time_raw(time_type)
                result = {"time": time_value}
                # 使用统一响应函数生成成功响应
                return self.handle_mcp_response(
                    parsed=parsed,
                    is_success=True,
                    result=result
                )
            
            elif parsed["method"] == "info" and parsed["func"] == "get":
                info_value = self.get_system_info_raw()
                result = {"system_info": info_value}
                # 使用统一响应函数生成成功响应
                return self.handle_mcp_response(
                    parsed=parsed,
                    is_success=True,
                    result=result
                )
            
            else:
                # 使用统一响应函数生成错误响应
                return self.handle_mcp_response(
                    parsed=parsed,
                    is_success=False,
                    error_code=1003,
                    error_msg=f"未知的方法组合: {full_method}，system模块仅支持 terminal.run / time.get / info.get"
                )
        
        except Exception as e:
            # 使用统一响应函数生成错误响应
            return self.handle_mcp_response(
                parsed=parsed,
                is_success=False,
                error_code=1004,
                error_msg=f"执行命令失败: {str(e)}"
            )
    
    def handle_python_module(self, parsed):
        """处理python模块的MCP请求（改造后：仅接收统一解析后的标准化数据）"""
        try:
            # 直接从统一解析结果中获取数据，无需再解析
            full_method = parsed["full_method"]
            params = parsed["params"]
            result = {}
            
            # Python模块只支持run.execute方法
            if parsed["method"] == "run" and parsed["func"] == "execute":
                # 遍历参数执行Python代码
                for param_key, param_value in params.items():
                    if param_key == "command":
                        # 单行Python命令
                        if not isinstance(param_value, str):
                            result[param_key] = f"错误: command必须是字符串类型，当前类型: {type(param_value).__name__}"
                            continue
                        # 执行单行Python代码
                        exec_result, exec_error = self.run_python_command(param_value)
                        if exec_error:
                            result[param_key] = f"执行错误: {exec_error}"
                        else:
                            result[param_key] = exec_result if exec_result is not None else "执行成功（无返回值）"
                    
                    elif param_key == "script":
                        # 多行Python脚本（列表形式）
                        if not isinstance(param_value, list):
                            result[param_key] = f"错误: script必须是列表类型，当前类型: {type(param_value).__name__}"
                            continue
                        # 检查列表元素是否都是字符串
                        if not all(isinstance(line, str) for line in param_value):
                            result[param_key] = "错误: script列表中的所有元素必须是字符串类型"
                            continue
                        # 执行多行Python脚本
                        exec_result, exec_error = self.run_python_script(param_value)
                        if exec_error:
                            result[param_key] = f"执行错误: {exec_error}"
                        else:
                            result[param_key] = exec_result if exec_result else "脚本执行成功（无输出）"
                    
                    else:
                        # 未知参数键
                        result[param_key] = f"错误: 不支持的参数键 '{param_key}'，仅支持 command/script"
                
                # 使用统一响应函数生成成功响应
                return self.handle_mcp_response(
                    parsed=parsed,
                    is_success=True,
                    result=result
                )
            
            else:
                # 使用统一响应函数生成错误响应
                return self.handle_mcp_response(
                    parsed=parsed,
                    is_success=False,
                    error_code=2001,
                    error_msg=f"Python模块未知的方法组合: {full_method}，仅支持 run.execute"
                )
        
        except Exception as e:
            # 使用统一响应函数生成错误响应
            return self.handle_mcp_response(
                parsed=parsed,
                is_success=False,
                error_code=2002,
                error_msg=f"执行Python代码失败: {str(e)}"
            )

    # ===================== 命令执行方法 =====================
    def run_terminal_command(self, command):
        """统一执行终端命令（移除powershell，仅保留通用shell）"""
        try:
            original_command = command
            os_type = platform.system()
            
            # 平台适配
            if os_type == "Windows":
                # Windows下使用cmd.exe执行
                if command.startswith("start "):
                    command = f"start /b {command[6:]}"
            elif os_type in ["Linux", "Darwin"]:
                # Linux/macOS下使用系统默认shell执行
                if not command.endswith("&"):
                    command = f"{command} &"

            # 打印要执行的命令日志（根据logger模式判断）
            logger_mode = self.config.logger
            if logger_mode in ["all", "format", "lite"]:
                print(f"[system@terminal:run] 执行终端命令: {original_command}")

            # 执行命令（统一使用shell=True）
            result = subprocess.run(
                command, 
                shell=True, 
                text=True, 
                capture_output=True,
                encoding='utf-8',
                errors='ignore'
            )

            output = result.stdout.strip()
            error = result.stderr.strip()

            # 打印命令执行结果日志（根据logger模式展示不同格式）
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "all":
                    if output:
                        print(f"[system@terminal:run] 命令输出: {output}")
                    if error:
                        print(f"[system@terminal:run] 命令错误: {error}")
                elif logger_mode == "format":
                    print(f"[system@terminal:run] 终端命令执行结果:")
                    if output:
                        print(f"  输出: {output}")
                    if error:
                        print(f"  错误: {error}")
                elif logger_mode == "lite":
                    # lite模式只显示简洁的执行结果
                    if error:
                        print(f"[system@terminal:run] 执行结果: 错误: {error}")
                    elif output:
                        print(f"[system@terminal:run] 执行结果: {output}")
                    else:
                        print(f"[system@terminal:run] 执行结果: 命令执行成功（无输出）")

            return output, error
        except Exception as e:
            # 异常信息根据logger模式显示
            logger_mode = self.config.logger
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "lite":
                    print(f"[system@terminal:run] 执行结果: 错误: {str(e)}")
                else:
                    print(f"[system@terminal:run] 终端命令执行错误: {str(e)}")
            return "", str(e)
    
    def run_python_command(self, command):
        """执行单行Python命令"""
        try:
            # 打印Python命令执行日志（根据logger模式判断）
            logger_mode = self.config.logger
            if logger_mode in ["all", "format", "lite"]:
                print(f"[python@run:execute] 执行Python命令: {command}")
            
            # 捕获标准输出
            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                try:
                    # 先尝试用eval执行（有返回值的表达式）
                    result = eval(command)
                    output = output_buffer.getvalue().strip()
                    # 如果有stdout输出，返回输出+返回值；否则只返回返回值
                    if output:
                        final_result = f"{output}\n返回值: {result}"
                    else:
                        final_result = result
                except SyntaxError:
                    # eval执行失败，用exec执行（无返回值的语句）
                    exec(command)
                    final_result = output_buffer.getvalue().strip()
                except:
                    # 其他错误，再次尝试exec
                    exec(command)
                    final_result = output_buffer.getvalue().strip()
            
            # 打印执行结果日志（根据logger模式展示不同格式）
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "all":
                    print(f"[python@run:execute] Python命令执行结果: {final_result if final_result else '无输出'}")
                elif logger_mode == "format":
                    print(f"[python@run:execute] Python命令执行结果:")
                    print(f"  输出: {final_result if final_result else '无输出'}")
                elif logger_mode == "lite":
                    # lite模式只显示简洁的执行结果
                    print(f"[python@run:execute] 执行结果: {final_result if final_result else '执行成功（无输出）'}")
            
            return final_result, ""
        
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            # 打印错误日志（根据logger模式显示）
            logger_mode = self.config.logger
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "lite":
                    print(f"[python@run:execute] 执行结果: 错误: {error_msg}")
                else:
                    print(f"[python@run:execute] Python命令执行错误: {error_msg}")
            return None, error_msg
    
    def run_python_script(self, script_lines):
        """执行多行Python脚本（从列表还原为脚本）"""
        try:
            # 将列表还原为完整的Python脚本
            script = "\n".join(script_lines)
            
            # 打印Python脚本执行日志（根据logger模式判断）
            logger_mode = self.config.logger
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "lite":
                    print(f"[python@run:execute] 执行Python脚本（共{len(script_lines)}行）")
                else:
                    print(f"[python@run:execute] 执行Python脚本:")
                    print(f"  脚本内容:")
                    for i, line in enumerate(script_lines, 1):
                        print(f"    {i}: {line}")
            
            # 捕获标准输出
            output_buffer = io.StringIO()
            with contextlib.redirect_stdout(output_buffer):
                exec(script)
            
            final_result = output_buffer.getvalue().strip()
            
            # 打印执行结果日志（根据logger模式展示不同格式）
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "all":
                    print(f"[python@run:execute] Python脚本执行结果: {final_result if final_result else '无输出'}")
                elif logger_mode == "format":
                    print(f"[python@run:execute] Python脚本执行结果:")
                    print(f"  输出: {final_result if final_result else '无输出'}")
                elif logger_mode == "lite":
                    # lite模式只显示简洁的执行结果
                    print(f"[python@run:execute] 执行结果: {final_result if final_result else '执行成功（无输出）'}")
            
            return final_result, ""
        
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            # 打印错误日志（根据logger模式显示）
            logger_mode = self.config.logger
            if logger_mode in ["all", "format", "lite"]:
                if logger_mode == "lite":
                    print(f"[python@run:execute] 执行结果: 错误: {error_msg}")
                else:
                    print(f"[python@run:execute] Python脚本执行错误: {error_msg}")
            return None, error_msg

    # ===================== 辅助方法 =====================
    def get_time_raw(self, time_type):
        """获取时间"""
        now = datetime.datetime.now()
        if time_type == "date":
            return now.strftime("%Y-%m-%d")
        elif time_type == "time":
            return now.strftime("%H:%M:%S")
        elif time_type == "stamp":
            return str(int(now.timestamp()))
        else:
            # 默认返回完整的日期时间
            return now.strftime("%Y-%m-%d %H:%M:%S")

    def get_system_info_raw(self):
        """获取系统信息"""
        return f"{platform.system()} {platform.release()}"

# ===================== 辅助函数 =====================
def clear():
    """清空屏幕"""
    os.system('cls' if os.name == 'nt' else 'clear')

# ===================== 主程序 =====================
if __name__ == "__main__":
    clear()
    # 启动LOGO
    print("""
██╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗
╚██╗     ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
 ╚██╗    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   
 ██╔╝    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   
██╔╝     ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   
╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   
""")

    # 初始化Agent（自动校验并修复配置）
    app = Agent()
    
    print("✅ Agent 已启动，输入消息开始对话，输入 ';;exit' 退出。")
    print("📚 支持的MCP操作（三级method格式）：")
    print("   - 终端命令：system.terminal.run（参数：command）")
    print("   - Python单行命令：python.run.execute (command参数)")
    print("   - Python多行脚本：python.run.execute (script参数，列表形式)")
    print("   - 时间查询：system.time.get")
    print("   - 系统信息：system.info.get")
    print("⚙️  日志模式说明：")
    print("   - all: 显示所有日志（MCP请求/响应+模块执行日志）")
    print("   - format: 格式化显示所有日志")
    print("   - lite: 仅显示模块执行结果（简洁模式），格式为 [模块名@方法名:函数名] 执行结果: 内容")
    print("   - None: 不显示任何日志")
    print(f"📁 提示词文件请放在 {os.path.abspath('prompt')} 文件夹中，支持.txt格式")
    print()
    
    while True:
        send_message = input(f"{app.config.user_name}: ")
        if send_message.lower() == ';;exit':
            clear()
            break
        elif send_message.strip() == ";;config":
            clear()
            print("""
 ██████╗ ██████╗ ███╗   ██╗███████╗██╗ ██████╗
██╔════╝██╔═══██╗████╗  ██║██╔════╝██║██╔════╝
██║     ██║   ██║██╔██╗ ██║█████╗  ██║██║  ███╗
██║     ██║   ██║██║╚██╗██║██╔══╝  ██║██║   ██║
╚██████╗╚██████╔╝██║ ╚████║██║     ██║╚██████╔╝
 ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝     ╚═╝ ╚═════╝
""")
            config_mode = True
            print("📋 可用命令：")
            print("   help      - 查看所有config命令的使用帮助")
            print("   cfghelp   - 查看所有配置项的详细说明")
            print("   watch     - 查看当前配置值")
            print("   set       - 设置配置项（用法：set <配置项> <值>）")
            print("   back      - 返回对话界面")
            print("   exit      - 退出程序")
            
            while config_mode:
                config_input = input("config> ").strip()
                if config_input.lower() == 'back':
                    clear()
                    print("""
██╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗
╚██╗     ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
 ╚██╗    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   
 ██╔╝    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   
██╔╝     ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   
╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   
""")
                    print("✅ 已返回对话界面，配置修改需重启程序生效")
                    config_mode = False
                elif config_input.lower() == 'watch':
                    print("\n当前配置：")
                    config_dict = app.config.model_dump()
                    for key, value in config_dict.items():
                        print(f"  {key}: {value}")
                    print()
                elif config_input.lower() == 'help':
                    # 显示config命令帮助
                    print("\n📖 Config菜单命令帮助：")
                    print("=" * 60)
                    print("1. help")
                    print("   作用：查看所有config菜单命令的使用帮助")
                    print("   用法：直接输入 help")
                    print()
                    print("2. cfghelp")
                    print("   作用：查看所有配置项的详细说明（包括作用、类型、默认值等）")
                    print("   用法：直接输入 cfghelp")
                    print()
                    print("3. watch")
                    print("   作用：查看当前所有配置项的取值")
                    print("   用法：直接输入 watch")
                    print()
                    print("4. set <配置项> <值>")
                    print("   作用：设置指定配置项的值")
                    print("   用法示例：")
                    print("      set logger lite")
                    print("      set send_history True")
                    print("      set api_key sk-xxxxxxxxxxxx")
                    print("      set prompt my_prompt.txt  # 设置prompt文件夹中的提示词文件")
                    print()
                    print("5. back")
                    print("   作用：返回主对话界面")
                    print("   用法：直接输入 back")
                    print()
                    print("6. exit")
                    print("   作用：退出整个程序")
                    print("   用法：直接输入 exit")
                    print("=" * 60)
                elif config_input.lower() == 'cfghelp':
                    # 显示配置项详细说明（原help功能）
                    print("\n📖 配置项详细说明：")
                    print("=" * 80)
                    config_help = {
                        "api_url": {
                            "作用": "AI API的请求地址",
                            "类型": "字符串",
                            "默认值": "https://api.example.com/v1/chat/completions",
                            "示例": "https://api.openai.com/v1/chat/completions"
                        },
                        "api_key": {
                            "作用": "AI API的认证密钥",
                            "类型": "字符串",
                            "默认值": "your_api_key_here",
                            "示例": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                        },
                        "model": {
                            "作用": "使用的AI模型名称",
                            "类型": "字符串",
                            "默认值": "default_model",
                            "示例": "gpt-3.5-turbo, gpt-4"
                        },
                        "user_name": {
                            "作用": "对话时显示的用户名",
                            "类型": "字符串",
                            "默认值": "用户",
                            "示例": "张三, User"
                        },
                        "ai_name": {
                            "作用": "对话时显示的AI名称",
                            "类型": "字符串",
                            "默认值": "AI",
                            "示例": "助手, ChatGPT"
                        },
                        "prompt": {
                            "作用": "prompt文件夹下的自定义提示词文件名（.txt格式）",
                            "类型": "字符串",
                            "默认值": "None",
                            "说明": """
  - 设置为None则不使用自定义提示词
  - 只需填写文件名，无需填写路径（文件必须放在prompt文件夹中）
  - 示例：set prompt my_prompt.txt"""
                        },
                        "send_history": {
                            "作用": "是否将当前会话历史发送给AI",
                            "类型": "布尔值",
                            "默认值": "False",
                            "合法值": "True/False"
                        },
                        "logger": {
                            "作用": "日志输出模式",
                            "类型": "字符串",
                            "默认值": "None",
                            "合法值": "all/format/lite/None",
                            "说明": """
  - all: 显示所有日志（MCP请求/响应+模块执行日志）
  - format: 格式化显示所有日志
  - lite: 仅显示模块执行结果（简洁模式）
  - None: 不显示任何日志"""
                        }
                    }
                    
                    # 格式化输出每个配置项的说明
                    for key, info in config_help.items():
                        print(f"\n🔧 {key}:")
                        for attr, value in info.items():
                            if attr == "说明" and "\n" in value:
                                print(f"   {attr}:{value}")
                            else:
                                print(f"   {attr}: {value}")
                    print("\n" + "=" * 80)
                elif config_input.lower().startswith("set "):
                    try:
                        parts = config_input.split(maxsplit=2)
                        if len(parts) < 3:
                            print("❌ 用法错误：set <配置项> <值>")
                            print("💡 示例：set logger lite 或 set send_history True")
                            print("💡 设置提示词文件：set prompt my_prompt.txt")
                            continue
                        
                        _, key, value = parts
                        # 严格校验配置值合法性
                        if key == "logger":
                            # 校验logger取值范围
                            valid_values = ["all", "format", "lite", "None"]
                            if value not in valid_values:
                                print(f"❌ 错误：{key} 只能设置为 {', '.join(valid_values)}")
                                continue
                            # 合法值：更新内存中的配置（保存到文件）
                            setattr(app.config, key, value)
                            app.save_config()
                        
                        elif key == "send_history":
                            if value.lower() == "true":
                                valid_value = True
                            elif value.lower() == "false":
                                valid_value = False
                            else:
                                print(f"❌ 错误：{key} 只能设置为 True/False")
                                continue
                            setattr(app.config, key, valid_value)
                            app.save_config()
                        
                        elif key in ["api_url", "api_key", "model", "user_name", "ai_name", "prompt"]:
                            # 字符串类型直接保存
                            setattr(app.config, key, value)
                            app.save_config()
                        
                        else:
                            print(f"❌ 未知的配置项: {key}")
                            print(f"💡 输入 cfghelp 查看所有可用配置项")
                            continue
                        
                        print(f"✅ 配置项 '{key}' 已更新为: {getattr(app.config, key)}")
                    
                    except Exception as e:
                        print(f"❌ 配置更新失败: {str(e)}")
                elif config_input.lower() == 'exit':
                    clear()
                    sys.exit()
                else:
                    print("❌ 未知命令！输入 help 查看所有可用命令")
        else:
            user_message = send_message.strip()
            app.send_message(user_message)

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

# ===================== 全局变量定义（MCP统一解析结果）=====================
# 全局存储MCP原生请求和解析后的标准化数据，所有模块直接使用
req = None       # 完整的原生MCP请求JSON字典
module = None    # 解析后的模块名（如system/python）
method = None    # 解析后的方法名（如terminal/run）
func = None      # 解析后的函数名（如run/execute）
params = {}      # 解析后的参数字典（始终为dict，默认空）
rawmet = None    # MCP请求里的完整method字段（三级格式：module.method.func）

# ===================== 配置项全局变量（与Config模型字段一一对应）=====================
# 所有配置值全局化，业务逻辑直接使用，由Agent统一维护同步
api_url = "https://api.example.com/v1/chat/completions"
api_key = "your_api_key_here"
model = "default_model"
user_name = "用户"
ai_name = "AI"
prompt = "None"  # 原prompt_file迁移后的字段
send_history = False
logger = "None"  # 可选值：all/format/lite/None

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

# ===================== 全局MCP统一解析函数 =====================
def parse_mcp_protocol(mcp_json, agent):
    """
    全局统一解析MCP协议请求，解析成功后赋值全局变量，失败则返回错误响应
    负责：格式合法性校验、核心字段提取、三级method解析、全局变量赋值
    :param mcp_json: 原始MCP请求JSON字典
    :param agent: Agent实例（用于生成错误响应）
    :return: 解析成功返回None，解析失败返回标准化MCP错误响应字符串
    """
    global req, module, method, func, params, rawmet
    # 解析前重置所有全局变量（避免脏数据）
    req = None
    module = None
    method = None
    func = None
    params = {}
    rawmet = None

    try:
        # 1. 基础格式校验：必须包含mcp和method字段
        if not isinstance(mcp_json, dict):
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1000,
                error_msg="MCP请求必须是JSON对象"
            )
        
        if "mcp" not in mcp_json:
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1001,
                error_msg="MCP请求缺少核心字段：mcp"
            )
        
        if mcp_json["mcp"] != "request":
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1002,
                error_msg=f"不支持的MCP类型：{mcp_json['mcp']}，仅支持request"
            )
        
        if "method" not in mcp_json:
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1003,
                error_msg="MCP请求缺少核心字段：method"
            )
        
        rawmet = mcp_json["method"]  # 完整三级method字段
        if not isinstance(rawmet, str) or not rawmet.strip():
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1004,
                error_msg="method字段必须是非空字符串"
            )
        
        # 2. 三级method解析（module.method.func）
        method_parts = rawmet.strip().split(".")
        if len(method_parts) != 3:
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1005,
                error_msg=f"method必须是三级格式：module.method.func，当前：{rawmet}"
            )
        
        module, method, func = method_parts
        if not all([module.strip(), method.strip(), func.strip()]):
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1006,
                error_msg="三级method的每一部分都不能为空"
            )
        
        # 3. 提取参数（params可选，默认空字典）
        params = mcp_json.get("params", {})
        if not isinstance(params, dict):
            return agent.handle_mcp_response(
                parsed={"full_method": "", "params": {}},
                is_success=False,
                error_code=1007,
                error_msg="params字段必须是JSON对象"
            )
        
        # 4. 解析成功：赋值全局变量（req为原生请求）
        req = mcp_json
        return None  # 无返回值表示解析成功

    except Exception as e:
        # 解析异常：返回标准化错误响应
        return agent.handle_mcp_response(
            parsed={"full_method": "", "params": {}},
            is_success=False,
            error_code=9999,
            error_msg=f"MCP协议解析异常：{str(e)}"
        )

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

# ===================== 核心工具函数：同步配置到全局变量 =====================
def sync_config_to_global(config_instance):
    """
    将Config实例的配置值同步到全局变量，保证全局变量与实例配置一致
    :param config_instance: Config模型实例
    """
    global api_url, api_key, model, user_name, ai_name, prompt, send_history, logger
    api_url = config_instance.api_url
    api_key = config_instance.api_key
    model = config_instance.model
    user_name = config_instance.user_name
    ai_name = config_instance.ai_name
    prompt = config_instance.prompt
    send_history = config_instance.send_history
    logger = config_instance.logger

# ===================== Agent类（包含MCP处理逻辑） =====================
class Agent:
    def __init__(self):
        """初始化Agent，加载并校验配置，同步到全局变量"""
        # 自动检测并创建prompt文件夹
        self.prompt_dir = "prompt"
        self.create_prompt_dir()
        
        # 加载配置并获取错误信息
        self.config, self.config_errors = Config.load_and_validate()
        # 关键：初始化时将配置同步到全局变量
        sync_config_to_global(self.config)
        
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
        """保存配置到文件，并同步到全局变量"""
        self.config.save_to_file()
        # 关键：保存后同步全局变量，保证全局值最新
        sync_config_to_global(self.config)
        print("✅ 配置已保存并同步到全局！")
    
    def log_ai_message(self, message):
        """统一的AI日志打印函数（使用全局logger变量）"""
        # 直接使用全局logger变量，替代self.config.logger
        if logger in ["all", "format"]:
            if isinstance(message, str) and message.startswith(";;") and message.endswith(";;"):
                json_str = message[2:-2]
                try:
                    json_data = json.loads(json_str)
                    if logger == "all":
                        print(f"[日志] {ai_name}: {json.dumps(json_data, ensure_ascii=False, separators=(',', ':'))}")
                    elif logger == "format":
                        print(f"[日志] {ai_name}:")
                        print(format_json_for_log(json_data, "  "))
                except json.JSONDecodeError:
                    print(f"[日志] {ai_name}: {message}")
            else:
                print(f"[日志] {ai_name}: {message}")

    def send_message(self, user_msg):
        """发送用户消息"""
        if not user_msg:
            return
        self.call_api(user_msg)

    def call_api(self, user_msg):
        """调用API获取AI响应（全程使用全局配置变量）"""
        try:
            # 直接使用全局ai_name、user_name变量
            system_content = f"你是一个名为{ai_name}的AI助手，正在与用户{user_name}对话。"
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

            # 加载prompt文件夹中的提示词文件（使用全局prompt变量）
            if prompt != "None":
                prompt_file_path = os.path.join(self.prompt_dir, prompt)
                try:
                    with open(prompt_file_path, "r", encoding="utf-8") as f:
                        prompt_content = f.read()
                    system_content += f"\n{prompt_content}"
                except FileNotFoundError:
                    self.log_ai_message(f"提示词文件不存在: {prompt_file_path}")
                except Exception as e:
                    self.log_ai_message(f"读取提示词文件失败: {str(e)}")

            messages = [{"role": "system", "content": system_content}]

            # 使用全局send_history变量判断是否发送历史
            if send_history:
                for entry in self.chat_history:
                    messages.append({"role": entry["role"], "content": entry["content"]})

            messages.append({"role": "user", "content": user_msg})

            # 调用API（使用全局api_url、api_key、model变量）
            response = requests.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": messages}
            )

            if response.status_code == 200:
                ai_resp = response.json().get("choices", [{}])[0].get("message", {}).get("content", "未获取到回复")
                self.handle_ai_response(ai_resp, user_msg)
            else:
                self.log_ai_message(f"错误: {response.text}")
        except Exception as e:
            self.log_ai_message(f"请求失败: {str(e)}")

    def handle_ai_response(self, ai_resp, user_msg):
        """处理AI响应"""
        mcp_pattern = r";;({.*?});;"
        mcp_matches = re.findall(mcp_pattern, ai_resp, re.DOTALL)
        
        if mcp_matches:
            for mcp_str in mcp_matches:
                try:
                    mcp_json = json.loads(mcp_str)
                    if mcp_json.get("mcp") == "request":
                        # 直接调用自身的MCP处理方法
                        mcp_resp = self.handle_mcp_request(mcp_json)
                        self.chat_history.append({"role": "assistant", "content": ai_resp})
                        self.call_api(mcp_resp)
                except json.JSONDecodeError as e:
                    error_msg = f"MCP JSON解析错误: {str(e)}"
                    self.log_ai_message(error_msg)
                except Exception as e:
                    error_msg = f"MCP处理错误: {str(e)}"
                    self.log_ai_message(error_msg)
        else:
            # 使用全局ai_name变量显示回复
            print(f"{ai_name}: {ai_resp}")
            self.chat_history.append({"role": "user", "content": user_msg})
            self.chat_history.append({"role": "assistant", "content": ai_resp})

    # ===================== 新增：统一的info构造函数 =====================
    def build_info_dict(self):
        """
        统一构造info字典（直接使用全局变量rawmet和params）
        :return: 标准化的info字典
        """
        return {
            "method": rawmet,  # 全局变量：完整三级方法名
            "params": params   # 全局变量：请求参数字典
        }

    # ===================== 新增：统一的响应处理函数 =====================
    def handle_mcp_response(self, is_success=True, result=None, error_code=None, error_msg=None):
        """
        统一处理MCP响应生成（直接使用全局变量）
        :param is_success: 是否成功（True/False）
        :param result: 成功时的结果数据（dict）
        :param error_code: 失败时的错误码（int）
        :param error_msg: 失败时的错误信息（str）
        :return: 格式化的MCP响应字符串
        """
        # 统一构造info字典（使用全局变量）
        info = self.build_info_dict()
        
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
        
        # 统一打印响应日志（根据全局logger变量）
        self.log_mcp_response(response_str)
        
        return response_str

    def log_mcp_response(self, response_str):
        """统一打印MCP响应日志（使用全局logger变量）"""
        if logger in ["all", "format"]:
            try:
                json_str = response_str[2:-2]
                json_data = json.loads(json_str)
                if logger == "all":
                    print(f"[日志] mcp返回:\n{json.dumps(json_data, ensure_ascii=False, separators=(',', ':'))}")
                elif logger == "format":
                    print(f"[日志] mcp返回:")
                    print(format_json_for_log(json_data, "  "))
            except:
                print(f"[日志] mcp返回: {response_str}")

    # ===================== 核心改造：MCP请求处理（仅调度，无解析） =====================
    def handle_mcp_request(self, mcp_json):
        """处理MCP请求并返回响应（仅负责调度，解析由全局函数完成）"""
        global req, module, method, func, params, rawmet
        # 1. 调用全局解析函数解析MCP请求
        parse_error = parse_mcp_protocol(mcp_json, self)
        if parse_error:
            # 解析失败：直接返回全局函数生成的错误响应
            return parse_error
        
        # 2. 解析成功：打印MCP请求日志（使用全局logger变量）
        if logger in ["all", "format"]:
            if logger == "all":
                print(f"[日志] mcp请求:\n{json.dumps(req, ensure_ascii=False, separators=(',', ':'))}")
            elif logger == "format":
                print(f"[日志] mcp请求:")
                print(format_json_for_log(req, "  "))
        
        # 3. 根据全局module变量调度业务处理（模块无需自行解析）
        if module == "system":
            return self.handle_system_module()
        elif module == "python":
            return self.handle_python_module()
        else:
            # 未知模块：返回标准化错误响应
            return self.handle_mcp_response(
                is_success=False,
                error_code=1002,
                error_msg=f"未知模块: {module}，仅支持system/python"
            )
    
    def handle_system_module(self):
        """处理system模块的MCP请求（直接使用全局变量，无任何解析逻辑）"""
        try:
            # 直接使用全局变量：method/func/params/rawmet，无需解析
            result = {}
            
            # system模块支持的方法：terminal.run, time.get, info.get
            if method == "terminal" and func == "run":
                # 直接使用全局params字典，仅处理command键
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
                # 返回成功响应（使用全局变量）
                return self.handle_mcp_response(is_success=True, result=result)
            
            elif method == "time" and func == "get":
                time_type = list(params.values())[0] if params else ""
                time_value = self.get_time_raw(time_type)
                result = {"time": time_value}
                # 返回成功响应
                return self.handle_mcp_response(is_success=True, result=result)
            
            elif method == "info" and func == "get":
                info_value = self.get_system_info_raw()
                result = {"system_info": info_value}
                # 返回成功响应
                return self.handle_mcp_response(is_success=True, result=result)
            
            else:
                # 未知的方法组合：返回错误响应
                return self.handle_mcp_response(
                    is_success=False,
                    error_code=1003,
                    error_msg=f"未知的方法组合: {rawmet}，system模块仅支持 terminal.run / time.get / info.get"
                )
        
        except Exception as e:
            # 执行异常：返回错误响应
            return self.handle_mcp_response(
                is_success=False,
                error_code=1004,
                error_msg=f"执行命令失败: {str(e)}"
            )
    
    def handle_python_module(self):
        """处理python模块的MCP请求（直接使用全局变量，无任何解析逻辑）"""
        try:
            # 直接使用全局变量：method/func/params/rawmet，无需解析
            result = {}
            
            # Python模块只支持run.execute方法
            if method == "run" and func == "execute":
                # 直接遍历全局params字典执行Python代码
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
                
                # 返回成功响应
                return self.handle_mcp_response(is_success=True, result=result)
            
            else:
                # 未知的方法组合：返回错误响应
                return self.handle_mcp_response(
                    is_success=False,
                    error_code=2001,
                    error_msg=f"Python模块未知的方法组合: {rawmet}，仅支持 run.execute"
                )
        
        except Exception as e:
            # 执行异常：返回错误响应
            return self.handle_mcp_response(
                is_success=False,
                error_code=2002,
                error_msg=f"执行Python代码失败: {str(e)}"
            )

    # ===================== 命令执行方法 =====================
    def run_terminal_command(self, command):
        """统一执行终端命令（移除powershell，仅保留通用shell，使用全局logger变量）"""
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

            # 打印要执行的命令日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
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

            # 打印命令执行结果日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
                if logger == "all":
                    if output:
                        print(f"[system@terminal:run] 命令输出: {output}")
                    if error:
                        print(f"[system@terminal:run] 命令错误: {error}")
                elif logger == "format":
                    print(f"[system@terminal:run] 终端命令执行结果:")
                    if output:
                        print(f"  输出: {output}")
                    if error:
                        print(f"  错误: {error}")
                elif logger == "lite":
                    # lite模式只显示简洁的执行结果
                    if error:
                        print(f"[system@terminal:run] 执行结果: 错误: {error}")
                    elif output:
                        print(f"[system@terminal:run] 执行结果: {output}")
                    else:
                        print(f"[system@terminal:run] 执行结果: 命令执行成功（无输出）")

            return output, error
        except Exception as e:
            # 异常信息根据全局logger变量显示
            if logger in ["all", "format", "lite"]:
                if logger == "lite":
                    print(f"[system@terminal:run] 执行结果: 错误: {str(e)}")
                else:
                    print(f"[system@terminal:run] 终端命令执行错误: {str(e)}")
            return "", str(e)
    
    def run_python_command(self, command):
        """执行单行Python命令（使用全局logger变量）"""
        try:
            # 打印Python命令执行日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
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
            
            # 打印执行结果日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
                if logger == "all":
                    print(f"[python@run:execute] Python命令执行结果: {final_result if final_result else '无输出'}")
                elif logger == "format":
                    print(f"[python@run:execute] Python命令执行结果:")
                    print(f"  输出: {final_result if final_result else '无输出'}")
                elif logger == "lite":
                    # lite模式只显示简洁的执行结果
                    print(f"[python@run:execute] 执行结果: {final_result if final_result else '执行成功（无输出）'}")
            
            return final_result, ""
        
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            # 打印错误日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
                if logger == "lite":
                    print(f"[python@run:execute] 执行结果: 错误: {error_msg}")
                else:
                    print(f"[python@run:execute] Python命令执行错误: {error_msg}")
            return None, error_msg
    
    def run_python_script(self, script_lines):
        """执行多行Python脚本（从列表还原为脚本，使用全局logger变量）"""
        try:
            # 将列表还原为完整的Python脚本
            script = "\n".join(script_lines)
            
            # 打印Python脚本执行日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
                if logger == "lite":
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
            
            # 打印执行结果日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
                if logger == "all":
                    print(f"[python@run:execute] Python脚本执行结果: {final_result if final_result else '无输出'}")
                elif logger == "format":
                    print(f"[python@run:execute] Python脚本执行结果:")
                    print(f"  输出: {final_result if final_result else '无输出'}")
                elif logger == "lite":
                    # lite模式只显示简洁的执行结果
                    print(f"[python@run:execute] 执行结果: {final_result if final_result else '执行成功（无输出）'}")
            
            return final_result, ""
        
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            # 打印错误日志（使用全局logger变量）
            if logger in ["all", "format", "lite"]:
                if logger == "lite":
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

    # 初始化Agent（自动校验并修复配置，同步到全局变量）
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
        # 使用全局user_name变量显示输入提示符
        send_msg = input(f"{user_name}: ")
        if send_msg.lower() == ';;exit':
            clear()
            break
        elif send_msg.strip() == ";;config":
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
                    print("✅ 已返回对话界面，配置修改已实时同步到全局！")
                    config_mode = False
                elif config_input.lower() == 'watch':
                    print("\n当前全局配置：")
                    # 直接打印全局变量，展示最新配置
                    print(f"  api_url: {api_url}")
                    print(f"  api_key: {api_key}")
                    print(f"  model: {model}")
                    print(f"  user_name: {user_name}")
                    print(f"  ai_name: {ai_name}")
                    print(f"  prompt: {prompt}")
                    print(f"  send_history: {send_history}")
                    print(f"  logger: {logger}")
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
                    print("   作用：查看当前所有全局配置项的取值")
                    print("   用法：直接输入 watch")
                    print()
                    print("4. set <配置项> <值>")
                    print("   作用：设置指定配置项的值，实时同步到全局")
                    print("   用法示例：")
                    print("      set logger lite")
                    print("      set send_history True")
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
                    print("\n📖 全局配置项详细说明：")
                    print("=" * 80)
                    config_help = {
                        "api_url": {
                            "作用": "AI API的请求地址（全局变量）",
                            "类型": "字符串",
                            "默认值": "https://api.example.com/v1/chat/completions",
                            "示例": "https://api.openai.com/v1/chat/completions"
                        },
                        "api_key": {
                            "作用": "AI API的认证密钥（全局变量）",
                            "类型": "字符串",
                            "默认值": "your_api_key_here",
                            "示例": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                        },
                        "model": {
                            "作用": "使用的AI模型名称（全局变量）",
                            "类型": "字符串",
                            "默认值": "default_model",
                            "示例": "gpt-3.5-turbo, gpt-4"
                        },
                        "user_name": {
                            "作用": "对话时显示的用户名（全局变量，输入提示符使用）",
                            "类型": "字符串",
                            "默认值": "用户",
                            "示例": "张三, User"
                        },
                        "ai_name": {
                            "作用": "对话时显示的AI名称（全局变量，回复前缀使用）",
                            "类型": "字符串",
                            "默认值": "AI",
                            "示例": "助手, ChatGPT"
                        },
                        "prompt": {
                            "作用": "prompt文件夹下的自定义提示词文件名（全局变量）",
                            "类型": "字符串",
                            "默认值": "None",
                            "说明": """
  - 设置为None则不使用自定义提示词
  - 只需填写文件名，无需填写路径（文件必须放在prompt文件夹中）
  - 示例：set prompt my_prompt.txt"""
                        },
                        "send_history": {
                            "作用": "是否将当前会话历史发送给AI（全局变量）",
                            "类型": "布尔值",
                            "默认值": "False",
                            "合法值": "True/False"
                        },
                        "logger": {
                            "作用": "日志输出模式（全局变量，所有日志逻辑使用）",
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
                    
                    # 格式化输出每个全局配置项的说明
                    for key, info in config_help.items():
                        print(f"\n🔧 {key}（全局变量）:")
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
                        # 严格校验配置值合法性，更新实例后同步到全局
                        if key == "logger":
                            # 校验logger取值范围
                            valid_values = ["all", "format", "lite", "None"]
                            if value not in valid_values:
                                print(f"❌ 错误：全局变量 {key} 只能设置为 {', '.join(valid_values)}")
                                continue
                            # 合法值：更新实例配置，保存并同步到全局
                            setattr(app.config, key, value)
                            app.save_config()
                        
                        elif key == "send_history":
                            if value.lower() == "true":
                                valid_value = True
                            elif value.lower() == "false":
                                valid_value = False
                            else:
                                print(f"❌ 错误：全局变量 {key} 只能设置为 True/False")
                                continue
                            setattr(app.config, key, valid_value)
                            app.save_config()
                        
                        elif key in ["api_url", "api_key", "model", "user_name", "ai_name", "prompt"]:
                            # 字符串类型直接更新，保存并同步到全局
                            setattr(app.config, key, value)
                            app.save_config()
                        
                        else:
                            print(f"❌ 未知的全局配置项: {key}")
                            print(f"💡 输入 cfghelp 查看所有可用全局配置项")
                            continue
                        
                        # 打印全局变量的最新值
                        print(f"✅ 全局配置项 '{key}' 已更新为: {globals()[key]}")
                    
                    except Exception as e:
                        print(f"❌ 全局配置更新失败: {str(e)}")
                elif config_input.lower() == 'exit':
                    clear()
                    sys.exit()
                else:
                    print("❌ 未知命令！输入 help 查看所有可用命令")
        else:
            user_msg = send_msg.strip()
            app.send_message(user_msg)
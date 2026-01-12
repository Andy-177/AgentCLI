import json
import os
import requests
import subprocess
import re
import platform
import datetime
from pydantic import BaseModel
import sys
from datetime import datetime

# 定义配置模型
class Config(BaseModel):
    api_url: str = "https://api.example.com/v1/chat/completions"
    api_key: str = "your_api_key_here"
    model: str = "default_model"
    user_name: str = "用户"
    ai_name: str = "AI"
    prompt_file: str = "None"
    log_commands: bool = False
    send_history: bool = False
    save_history: bool = False
    send_saved_history: bool = False
    logger: str = "None"  # 可选值：all/format/None

    def save_to_file(self, file_path="config.json"):
        """保存配置到文件"""
        # 替换：dict() → model_dump()
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
        # 替换：dict() → model_dump()
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
            error_time = datetime.now().strftime("%Y%m%d_%H%M%S")
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
            
            # 校验并修复配置项
            if key == "logger":
                # 校验logger取值范围
                if user_value not in ["all", "format", "None"]:
                    config_errors.append({
                        "item": key,
                        "original_value": user_value,
                        "error_reason": "取值不在允许范围内（all/format/None）",
                        "fixed_value": default_value
                    })
                    validated_data[key] = default_value
                else:
                    validated_data[key] = user_value
            
            elif key in ["log_commands", "send_history", "save_history", "send_saved_history"]:
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
            
            elif key in ["api_url", "api_key", "model", "user_name", "ai_name", "prompt_file"]:
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

# ===================== MCP类 =====================
class mcp:
    def __init__(self, chat_method):
        self.chat_method = chat_method
    
    def parse_mcp_request(self, mcp_json):
        """解析MCP请求JSON"""
        try:
            method_parts = mcp_json.get("method", "").split(".")
            method_name = method_parts[0] if len(method_parts) > 0 else ""
            func_name = method_parts[1] if len(method_parts) > 1 else ""
            
            return {
                "id": mcp_json.get("id", ""),
                "module": mcp_json.get("module", ""),
                "method": method_name,
                "func": func_name,
                "full_method": mcp_json.get("method", ""),
                "params": mcp_json.get("params", {})
            }
        except Exception as e:
            return {"error": f"解析MCP请求失败: {str(e)}"}
    
    def handle_mcp_request(self, mcp_json):
        """处理MCP请求并返回响应"""
        logger_mode = self.chat_method.config.logger
        if logger_mode in ["all", "format"]:
            if logger_mode == "all":
                print(f"[日志] mcp请求:\n{json.dumps(mcp_json, ensure_ascii=False, separators=(',', ':'))}")
            elif logger_mode == "format":
                print(f"[日志] mcp请求:")
                print(format_json_for_log(mcp_json, "  "))
        
        parsed = self.parse_mcp_request(mcp_json)
        if "error" in parsed:
            response = self.build_error_response(
                mcp_json.get("id", "unknown"),
                {"module": "system", "method": "parse.error", "params": {}},
                1001,
                parsed["error"]
            )
            if logger_mode in ["all", "format"]:
                if logger_mode == "all":
                    print(f"[日志] mcp返回:\n{json.dumps(json.loads(response[2:-2]), ensure_ascii=False, separators=(',', ':'))}")
                elif logger_mode == "format":
                    print(f"[日志] mcp返回:")
                    if response.startswith(";;") and response.endswith(";;"):
                        json_str = response[2:-2]
                        print(format_json_for_log(json_str, "  "))
                    else:
                        print(f"  {response}")
            return response
        
        module = parsed["module"]
        if module == "system":
            response = self.handle_system_module(parsed)
        else:
            response = self.build_error_response(
                parsed["id"],
                {"module": module, "method": parsed.get("full_method", ""), "params": parsed.get("params", {})},
                1002,
                f"未知模块: {module}"
            )
        
        if logger_mode in ["all", "format"]:
            if logger_mode == "all":
                print(f"[日志] mcp返回:\n{json.dumps(json.loads(response[2:-2]), ensure_ascii=False, separators=(',', ':'))}")
            elif logger_mode == "format":
                print(f"[日志] mcp返回:")
                if response.startswith(";;") and response.endswith(";;"):
                    json_str = response[2:-2]
                    print(format_json_for_log(json_str, "  "))
                else:
                    print(f"  {response}")
        
        return response
    
    def handle_system_module(self, parsed):
        """处理system模块的MCP请求"""
        method = parsed["method"]
        func = parsed["func"]
        full_method = parsed["full_method"]
        params = parsed["params"]
        result = {}
        
        info = {
            "module": parsed["module"],
            "method": full_method,
            "params": params
        }
        
        try:
            if method == "run" and func in ["cmd", "powershell", "shell"]:
                for cmd_key, cmd_value in params.items():
                    if cmd_value.strip():
                        output, error = self.chat_method.run_command_raw(func, cmd_value)
                        if error:
                            result[cmd_key] = f"错误: {error}"
                        elif output:
                            result[cmd_key] = output.strip()
                        else:
                            result[cmd_key] = "命令执行成功（无输出）"
                return self.build_success_response(parsed["id"], info, result)
            
            elif method == "time" and func == "get":
                time_type = list(params.values())[0] if params else ""
                time_value = self.chat_method.get_time_raw(time_type)
                result = {"time": time_value}
                return self.build_success_response(parsed["id"], info, result)
            
            elif method == "info" and func == "get":
                info_value = self.chat_method.get_system_info_raw()
                result = {"system_info": info_value}
                return self.build_success_response(parsed["id"], info, result)
            
            else:
                return self.build_error_response(
                    parsed["id"],
                    info,
                    1003,
                    f"未知的方法/函数组合: {method}.{func}"
                )
        
        except Exception as e:
            return self.build_error_response(
                parsed["id"],
                info,
                1004,
                f"执行命令失败: {str(e)}"
            )
    
    def build_success_response(self, req_id, info, result):
        """构建成功的MCP响应"""
        response = {
            "mcp": "response",
            "id": req_id,
            "info": info,
            "result": result
        }
        return f";;{json.dumps(response, ensure_ascii=False, separators=(',', ':'))};;"
    
    def build_error_response(self, req_id, info, error_code, error_msg):
        """构建错误的MCP响应"""
        response = {
            "mcp": "response",
            "id": req_id,
            "info": info,
            "error": {
                "code": error_code,
                "message": error_msg
            }
        }
        return f";;{json.dumps(response, ensure_ascii=False, separators=(',', ':'))};;"

# ===================== Agent类 =====================
class Agent:
    def __init__(self):
        """初始化Agent，加载并校验配置"""
        # 加载配置并获取错误信息
        self.config, self.config_errors = Config.load_and_validate()
        self.prompt_files = self.get_prompt_files()
        self.chat_history = []
        self.saved_history = self.load_saved_history()
        self.mcp = mcp(self)
        
        # 打印配置错误提示（如果有）
        self.print_config_errors()

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
        """获取根目录下的所有 .txt 文件"""
        files = [f for f in os.listdir() if f.endswith('.txt')]
        return ["无"] + files

    def save_config(self):
        """保存配置（仅当通过config命令设置合法值时）"""
        self.config.save_to_file()
        print("✅ 配置已保存！")
    
    def log_ai_message(self, message):
        """统一的AI日志打印函数"""
        logger_mode = self.config.logger
        if logger_mode not in ["all", "format"]:
            return
        
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
            system_content += "\n;;{\"mcp\":\"request\",\"id\":\"001\",\"module\":\"system\",\"method\":\"run.shell\",\"params\":{\"command1\":\"echo hello\",\"command2\":\"echo world\"}};;"
            system_content += "\n支持的MCP操作："
            system_content += "\n1. 执行命令：module=system, method=run.cmd/run.powershell/run.shell, params={命令键: 命令值}"
            system_content += "\n2. 获取时间：module=system, method=time.get, params={type: date/time/stamp/(空)}"
            system_content += "\n3. 获取系统信息：module=system, method=info.get, params={}"
            system_content += "\n注意：收到MCP响应后，不需要再次生成MCP请求，直接用自然语言回复用户即可"

            if self.config.prompt_file != "None":
                try:
                    with open(self.config.prompt_file, "r", encoding="utf-8") as f:
                        prompt_content = f.read()
                    system_content += f"\n{prompt_content}"
                except Exception as e:
                    self.log_ai_message(f"读取提示词文件失败: {str(e)}")

            if self.config.send_saved_history:
                for entry in self.saved_history:
                    system_content += f"\n{entry['role']}: {entry['content']}"

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
                        mcp_response = self.mcp.handle_mcp_request(mcp_json)
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

            if self.config.save_history:
                self.save_chat_history(user_message, ai_response)

    def run_command_raw(self, command_type, command):
        """执行命令并返回输出和错误信息"""
        try:
            original_command = command
            if platform.system() == "Windows":
                if command_type == "shell":
                    command_type = "cmd"
                if command.startswith("start "):
                    command = f"start /b {command[6:]}"
            elif platform.system() == "Linux" or platform.system() == "Darwin":
                if command_type == "cmd":
                    command_type = "shell"
                if not command.endswith("&"):
                    command = f"{command} &"

            # 打印要执行的命令日志
            logger_mode = self.config.logger
            if logger_mode in ["all", "format"] and self.config.log_commands:
                print(f"[日志] 执行命令({command_type}): {original_command}")

            # 执行命令
            if command_type == "cmd":
                result = subprocess.run(command, shell=True, text=True, capture_output=True)
            elif command_type == "shell":
                result = subprocess.run(command, shell=True, text=True, capture_output=True)
            elif command_type == "powershell":
                result = subprocess.run(["powershell", "-Command", command], text=True, capture_output=True)
            else:
                return "", f"未知命令类型: {command_type}"

            output = result.stdout.strip()
            error = result.stderr.strip()

            # 打印命令执行结果日志
            if logger_mode in ["all", "format"] and self.config.log_commands:
                if logger_mode == "all":
                    if output:
                        print(f"[日志] 命令({command_type})输出: {output}")
                    if error:
                        print(f"[日志] 命令({command_type})错误: {error}")
                elif logger_mode == "format":
                    print(f"[日志] 命令({command_type})执行结果:")
                    if output:
                        print(f"  输出: {output}")
                    if error:
                        print(f"  错误: {error}")

            return output, error
        except Exception as e:
            return "", str(e)

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
            return now.strftime("%Y-%m-%d %H:%M:%S")

    def get_system_info_raw(self):
        """获取系统信息"""
        return f"{platform.system()}"

    def save_chat_history(self, user_message, ai_response):
        """保存聊天记录"""
        history_file = "history.hty"
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(f"{self.config.user_name}: {user_message}\n")
            f.write(f"{self.config.ai_name}: {ai_response}\n")

    def load_saved_history(self):
        """加载已保存的历史记录"""
        history_file = "history.hty"
        saved_history = []
        if os.path.exists(history_file):
            with open(history_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for i in range(0, len(lines), 2):
                    user_message = lines[i].strip()
                    ai_response = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    saved_history.append({"role": "user", "content": user_message})
                    saved_history.append({"role": "assistant", "content": ai_response})
        return saved_history

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
    
    print("Agent 已启动，输入消息开始对话，输入 ';;exit' 退出。")
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
            print("📋 输入 watch 查看当前配置")
            print("📝 输入 set logger all/format/None 配置日志模式")
            print("📝 输入 set log_commands True/False 配置命令日志开关")
            print("🔙 输入 back 返回对话界面")
            print("🚪 输入 exit 退出程序")
            
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
                    print("已返回对话界面，配置修改需重启程序生效")
                    config_mode = False
                elif config_input.lower() == 'watch':
                    print("\n当前配置：")
                    # 替换：dict() → model_dump()
                    config_dict = app.config.model_dump()
                    for key, value in config_dict.items():
                        print(f"  {key}: {value}")
                    print()
                elif config_input.lower().startswith("set "):
                    try:
                        parts = config_input.split(maxsplit=2)
                        if len(parts) < 3:
                            print("❌ 用法: set <配置项> <值>")
                            continue
                        
                        _, key, value = parts
                        # 严格校验配置值合法性
                        if key == "logger":
                            if value not in ["all", "format", "None"]:
                                print(f"❌ 错误：{key} 只能设置为 all/format/None")
                                continue
                            # 合法值：更新内存中的配置（保存到文件）
                            setattr(app.config, key, value)
                            app.save_config()
                        
                        elif key == "log_commands":
                            if value.lower() == "true":
                                valid_value = True
                            elif value.lower() == "false":
                                valid_value = False
                            else:
                                print(f"❌ 错误：{key} 只能设置为 True/False")
                                continue
                            # 合法值：更新内存中的配置（保存到文件）
                            setattr(app.config, key, valid_value)
                            app.save_config()
                        
                        elif key in ["send_history", "save_history", "send_saved_history"]:
                            if value.lower() == "true":
                                valid_value = True
                            elif value.lower() == "false":
                                valid_value = False
                            else:
                                print(f"❌ 错误：{key} 只能设置为 True/False")
                                continue
                            setattr(app.config, key, valid_value)
                            app.save_config()
                        
                        elif key in ["api_url", "api_key", "model", "user_name", "ai_name", "prompt_file"]:
                            # 字符串类型直接保存
                            setattr(app.config, key, value)
                            app.save_config()
                        
                        else:
                            print(f"❌ 未知的配置项: {key}")
                            continue
                        
                        print(f"✅ 配置项 '{key}' 已更新为: {getattr(app.config, key)}")
                    
                    except Exception as e:
                        print(f"❌ 配置更新失败: {str(e)}")
                elif config_input.lower() == 'exit':
                    clear()
                    sys.exit()
                else:
                    print("❌ 未知命令，请输入 'watch' / 'set <配置项> <值>' / 'back' / 'exit'")
        else:
            user_message = send_message.strip()
            app.send_message(user_message)

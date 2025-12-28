import json
import os
import requests
import subprocess
import re
import platform
from pydantic import BaseModel
import sys
# 定义配置模型
class Config(BaseModel):
    api_url: str = "https://api.example.com/v1/chat/completions"
    api_key: str = "your_api_key_here"
    model: str = "default_model"
    user_name: str = "用户"
    ai_name: str = "AI"
    prompt_file: str = "无"
    log_commands: bool = False
    send_history: bool = False
    save_history: bool = False
    send_saved_history: bool = False

    def save_to_file(self, file_path="config.json"):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.dict(), f, indent=4)

    @classmethod
    def load_from_file(cls, file_path="config.json"):
        if not os.path.exists(file_path):
            return cls()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(**data)
        except json.JSONDecodeError:
            return cls()

# 定义聊天工具类
class AIChatTool:
    def __init__(self):
        self.config = Config.load_from_file()
        self.prompt_files = self.get_prompt_files()
        self.chat_history = []
        self.saved_history = self.load_saved_history()

    def get_prompt_files(self):
        """获取根目录下的所有 .txt 文件"""
        files = [f for f in os.listdir() if f.endswith('.txt')]
        return ["无"] + files

    def save_config(self):
        self.config.save_to_file()
        print("配置已保存！")

    def send_message(self, user_message):
        if not user_message:
            return
        self.call_api(user_message)  # 直接调用 call_api，不再使用线程

    def call_api(self, user_message):
        try:
            system_content = f"你是一个名为{self.config.ai_name}的AI助手，正在与用户{self.config.user_name}对话。"
            system_content += f"\n当前系统类型是：{platform.system()}"
            system_content += "\n你可以使用以下命令格式："
            system_content += "\n~!run:[cmd:<命令>]!~ 执行命令行命令"
            system_content += "\n~!run:[shell:<命令>]!~ 执行 Shell 命令"
            system_content += "\n~!run:[ps:<命令>]!~ 执行 PowerShell 命令"
            system_content += "\n~!get:[systype]!~ 获取当前系统类型"

            # 如果选择了提示词文件，则读取文件内容并追加到系统提示词
            if self.config.prompt_file != "无":
                with open(self.config.prompt_file, "r", encoding="utf-8") as f:
                    prompt_content = f.read()
                system_content += f"\n{prompt_content}"

            # 如果发送已保存的历史记录选项被勾选，则读取并添加已保存的历史记录
            if self.config.send_saved_history:
                for entry in self.saved_history:
                    system_content += f"\n{entry['role']}: {entry['content']}"

            # 构建消息列表
            messages = [
                {
                    "role": "system",
                    "content": system_content
                }
            ]

            # 如果发送历史记录选项被勾选，则将聊天历史添加到消息列表中
            if self.config.send_history:
                for entry in self.chat_history:
                    messages.append({"role": entry["role"], "content": entry["content"]})

            # 添加当前用户消息
            messages.append({
                "role": "user",
                "content": user_message
            })

            response = requests.post(
                self.config.api_url,
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                json={"model": self.config.model, "messages": messages}
            )

            if response.status_code == 200:
                ai_response = response.json().get("choices", [{}])[0].get("message", {}).get("content", "未获取到回复")
                self.handle_ai_response(ai_response, user_message)  # 传入 user_message
            else:
                print(f"{self.config.ai_name}: 错误: {response.text}")
        except Exception as e:
            print(f"{self.config.ai_name}: 请求失败: {str(e)}")

    def handle_ai_response(self, ai_response, user_message):
        # 只打印 AI 的回复，不打印用户消息
        pattern = r"~!run:\[(cmd|shell|ps):(.+?)\]!~"
        matches = re.findall(pattern, ai_response)

        if matches:
            for match in matches:
                command_type = match[0]
                command = match[1].strip()
                if self.config.log_commands:
                    print(f"[日志] 执行命令: {command}")
                self.run_command(command_type, command)  # 直接调用 run_command，不再使用线程
        else:
            print(f"{self.config.ai_name}: {ai_response}")

        # 将用户消息和 AI 回复添加到聊天历史中
        self.chat_history.append({"role": "user", "content": user_message})
        self.chat_history.append({"role": "assistant", "content": ai_response})

        # 如果保存历史记录选项被勾选，则将聊天记录保存到文件
        if self.config.save_history:
            self.save_chat_history(user_message, ai_response)

    def run_command(self, command_type, command):
        try:
            if command_type == "cmd":
                result = subprocess.run(command, shell=True, text=True, capture_output=True)
            elif command_type == "shell":
                result = subprocess.run(command, shell=True, text=True, capture_output=True)
            elif command_type == "ps":
                result = subprocess.run(["powershell", "-Command", command], text=True, capture_output=True)
            else:
                print(f"{self.config.ai_name}: 未知命令类型")
                return

            output = result.stdout.strip()
            error = result.stderr.strip()

            if self.config.log_commands:
                print(f"[日志] 命令输出: {output}")
                if error:
                    print(f"[日志] 命令错误: {error}")

            if not output and not error:
                self.call_api("没有返回内容")
            else:
                response_content = f"命令输出: {output}\n命令错误: {error}\n" if error else f"命令输出: {output}\n"
                self.call_api(response_content)
        except Exception as e:
            print(f"命令执行失败: {str(e)}")

    def save_chat_history(self, user_message, ai_response):
        """将聊天记录保存到文件"""
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

def clear():
    """清空屏幕"""
    os.system('cls' if os.name == 'nt' else 'clear')
# 运行程序
if __name__ == "__main__":
    clear()
    # 启动时打印的 ASCII 图案
    print("""
██╗       █████╗  ██████╗ ███████╗███╗   ██╗████████╗
╚██╗     ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
 ╚██╗    ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
 ██╔╝    ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
██╔╝     ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝
""")

    app = AIChatTool()
    print("AI Chat Tool 已启动，输入消息开始对话，输入 ';;exit' 退出。")
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
            print("输入watch查看当前配置")
            while config_mode:
                config_input = input("config>")
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
                    print("配置没有重载，建议重启程序以应用更改")
                    config_mode = False
                elif config_input.lower() == 'watch':
                    with open('config.json', 'r', encoding='utf-8') as file:
                        data = json.load(file)
                    for key, value in data.items():
                        print(f"{key}: {value}")
                elif config_input.split()[0].lower() == "set":
                    try:
                        _, key, value = config_input.split()
                        with open('config.json', 'r', encoding='utf-8') as file:
                            data = json.load(file)
                        data[key] = value
                        with open('config.json', 'w', encoding='utf-8') as file:
                            json.dump(data, file, indent=4, ensure_ascii=False)
                        print(f"配置项 '{key}' 已更新为: {value}")
                    except ValueError:
                        print("用法: set <配置项> <值>")
                    except KeyError:
                        print(f"未知的配置项: {key}")
                    except Exception as e:
                        print(f"发生错误: {e}")
                elif config_input.strip() == "exit":
                    clear()
                    exit()
                else:
                    print("未知命令，请输入 'watch' 或 'set <配置项> <值>'")
        else:
            user_message = send_message.strip()
            app.send_message(user_message)
# AgentCLI
A Super Agent
# 注意
**必须安装pydantic库和requests库**
## 安装命令
> pydantic库
> ```
> pip install pydantic
> ```
> requests库
> ```
> pip install requests
> ```
# 帮助
在`AGENT`界面使用;;exit命令退出AgentCLI，使用;;config命令打开配置界面
# 更新日志
## Release-1.1.0
- ## 更新
  - 1.把system模块里的run方法改为terminal，cmd和shell合并为run函数
  - 2.彻底抛弃powershell
  - 3.添加python模块，允许Agent执行python代码
  - 4.删除了log_commands配置，改为logger里的lite选项
  - 5.修改了日志格式，日志标识从`[日志]`改为`[模块名@方法名:函数]`的格式，类似之前的cmcp或linux的命令提示符
  - 6.在config模式添加了`help`命令，使用help查看所有config命令说明，添加`cfghelp`命令，查看所有配置项用途
- ## 未来
  - [ ] 允许自己编写mcp模块
  - [ ] 将powershell做成mcp模块，让有需求的用户可以使用
## Release-1.0.0
- ## 更新
  - 1.彻底修改mcp协议，抛弃了原来的cmcp协议，改用更标准的mcp协议
  - 2.可以自动修改错误的配置项，config不会允许用户将配置项修改错误
  - 3.没有配置时自动创建默认配置
- ## 未来
  - [ ] 允许自己编写mcp模块
  - [ ] 允许让ai执行python

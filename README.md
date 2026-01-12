# AgentCLI
A Super Agent
# 注意
**必须安装pydantic库和requests库**
## 安装命令
pydantic库
```
pip install pydantic
```
requests库
```
pip install requests
```
# 更新日志
## 1.0.0
- ## 更新
  - 1.彻底修改mcp协议，抛弃了原来的cmcp协议，改用更标准的mcp协议
  - 2.可以自动修改错误的配置项，config不会允许用户将配置项修改错误
  - 3.没有配置时自动创建默认配置
- ## 未来
- [ ] 允许自己编写mcp模块
- [ ] 允许让ai执行python

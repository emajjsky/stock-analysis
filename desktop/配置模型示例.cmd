@echo off
chcp 65001 >nul
rem 仅在自己的本地副本填写；不要把含密钥的文件提交或分享。
rem Jev使用TypeSafe官方接口，无密钥时不发请求。
rem set "TYPESAFE_API_KEY=填写自己的密钥"
rem set "JEV_MODEL=jev-latest"
rem Agent复核使用OpenAI兼容接口，API_BASE包含/v1部分。
rem set "AGENT_API_BASE=https://你的模型服务/v1"
rem set "AGENT_MODEL=你的模型名"
rem set "AGENT_API_KEY=填写自己的密钥"
rem 可选：set "WANGZHA_DATA_DIR=D:\王炸数据"
start "" "%~dp0王炸.exe"

# 启动河狸官网服务
# 首次使用：复制 .env.example 为 .env，并填写 WECOM_WEBHOOK
$env:WECOM_WEBHOOK = $env:WECOM_WEBHOOK
$env:FEISHU_WEBHOOK = $env:FEISHU_WEBHOOK
uvicorn backend:app --host 127.0.0.1 --port 8931

# 内容审阅台部署手册

目标服务器：腾讯云 Lighthouse Ubuntu
项目目录：`/opt/ai-content-loop/repo`
运行用户：`agentuser`
本地监听：`127.0.0.1:8765`

审阅服务与每日内容生成服务相互独立。部署审阅台不会改变
`ai-content-loop.timer` 的执行时间或生成逻辑。

## 1. 安装 Python 运行环境

```bash
cd /opt/ai-content-loop/repo
sudo apt-get update
sudo apt-get install -y python3-venv fonts-noto-cjk
sudo python3 -m venv /opt/ai-content-loop/venv
sudo /opt/ai-content-loop/venv/bin/pip install --upgrade pip
sudo /opt/ai-content-loop/venv/bin/pip install -r requirements-review.txt
sudo chown -R root:root /opt/ai-content-loop/venv
```

确认中文字体已安装：

```bash
test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
```

在 `/opt/ai-content-loop/config.toml` 中配置本地视觉渲染。这里使用
Ubuntu 的 Noto CJK 系统字体路径；示例配置中的相对路径适合把字体随配置目录一起分发：

```toml
visual_font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
visual_render_concurrency = 1
```

## 2. 生成审阅凭据

生成会话密钥：

```bash
/opt/ai-content-loop/venv/bin/python -c \
  'import secrets; print(secrets.token_hex(32))'
```

交互式输入登录密码并生成哈希，密码不会显示：

```bash
/opt/ai-content-loop/venv/bin/python -c \
  'from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass("Review password: ")))'
```

创建仅 root 可读的环境文件：

```bash
sudo install -m 600 -o root -g root /dev/null \
  /opt/ai-content-loop/review.env
sudoedit /opt/ai-content-loop/review.env
```

内容如下，将两项占位值替换为上一步生成的结果：

```text
AI_CONTENT_CONFIG=/opt/ai-content-loop/config.toml
AI_CONTENT_REVIEW_USERNAME=owner
AI_CONTENT_REVIEW_PASSWORD_HASH=PASTE_THE_GENERATED_HASH_HERE
AI_CONTENT_REVIEW_SECRET_KEY=PASTE_THE_GENERATED_RANDOM_KEY_HERE
WECHAT_APP_ID=PASTE_THE_OFFICIAL_ACCOUNT_APP_ID_HERE
WECHAT_APP_SECRET=PASTE_THE_OFFICIAL_ACCOUNT_APP_SECRET_HERE
# 可选，默认 https://api.weixin.qq.com
# WECHAT_API_BASE_URL=https://api.weixin.qq.com
```

不要把明文密码、公众号 AppSecret 或 `review.env` 放进 Git。公众号凭据
缺失时按钮会显示“公众号未配置”，服务不会发起任何外部请求。该功能只调用
素材上传与 `draft/add` 创建草稿，严禁接入自动发布或群发接口。

## 3. 安装并启动 systemd 服务

```bash
cd /opt/ai-content-loop/repo
sudo cp deploy/systemd/ai-content-loop.service \
  /etc/systemd/system/ai-content-loop.service
sudo cp deploy/systemd/ai-content-review.service \
  /etc/systemd/system/ai-content-review.service
sudo systemd-analyze verify \
  /etc/systemd/system/ai-content-loop.service
sudo systemd-analyze verify \
  /etc/systemd/system/ai-content-review.service
sudo systemctl daemon-reload
sudo systemctl enable --now ai-content-review.service
sudo systemctl status ai-content-review.service --no-pager
```

本机验证：

```bash
curl -I http://127.0.0.1:8765/login
ss -lntp | grep 8765
```

预期：

- 登录页返回 HTTP 200。
- `8765` 只监听 `127.0.0.1`，不能出现 `0.0.0.0:8765`。
- 腾讯云防火墙不开放 TCP 8765。

## 4. 安装 Tailscale

根据服务器的 Ubuntu 代号添加 Tailscale 官方软件源：

```bash
. /etc/os-release
curl -fsSL \
  "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.noarmor.gpg" \
  | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL \
  "https://pkgs.tailscale.com/stable/ubuntu/${VERSION_CODENAME}.tailscale-keyring.list" \
  | sudo tee /etc/apt/sources.list.d/tailscale.list
sudo apt-get update
sudo apt-get install -y tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up
```

首次执行 `tailscale up` 会打印授权 URL。用浏览器打开并完成授权后继续。

## 5. 开启公网 HTTPS Funnel

```bash
sudo tailscale funnel --bg 8765
tailscale funnel status
TAILSCALE_HOST="$(
  tailscale status --json |
  python3 -c \
    'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
)"
echo "https://$TAILSCALE_HOST"
```

浏览器访问打印出的 HTTPS 地址。Funnel 会把公网 HTTPS 请求转发到
`http://127.0.0.1:8765`，无需开放 Lighthouse 入站端口。

## 6. 验收

```bash
curl -I "https://$TAILSCALE_HOST/login"
sudo systemctl is-active ai-content-review.service
sudo systemctl is-enabled ai-content-review.service
sudo systemctl is-active ai-content-loop.timer
tailscale funnel status
```

浏览器验收：

1. 未登录不能读取文章正文。
2. 登录后能看到现有文章。
3. 能切换母稿、公众号、小红书、今日头条和知乎。
4. 编辑正文后预览同步更新。
5. 保存后生成历史快照。
6. 能恢复旧版本。
7. 审核状态刷新后仍然保留。
8. 手机窄屏下能切换编辑和预览。
9. 已通过且未修改的文章可人工点击“同步公众号草稿”，公众号后台出现草稿；
   页面不会自动同步，也不会自动发布或群发。

## 7. 日志

```bash
journalctl -u ai-content-review.service -n 100 --no-pager
journalctl -u ai-content-loop.service -n 100 --no-pager
```

日志中不得记录密码、密码哈希、会话密钥或正文全文。

## 8. 回退

关闭公网入口：

```bash
sudo tailscale funnel reset
```

停止审阅服务：

```bash
sudo systemctl disable --now ai-content-review.service
```

这不会停止每日内容生成任务，也不会删除 `out/final`、`out/history`
或 SQLite 数据。

如果 Funnel 在当前网络中不稳定，改用仅个人设备可访问的 Serve：

```bash
sudo tailscale serve --bg 8765
tailscale serve status
```

# 腾讯云 Lighthouse 部署方案

## 结论

可以部署在腾讯云轻量应用服务器 Lighthouse，而且很适合这个只有两名真实用户的首版产品。Lighthouse 能运行 Docker 容器、绑定域名并配置 HTTPS；腾讯云官方文档也提供 Docker 环境和容器管理路径。

但需要区分两个阶段：

- **当前前端原型**：只需把 `npm run build` 生成的 `dist/` 放进 Nginx/Caddy，即可通过网页访问。
- **正式双人版本**：必须增加服务端登录、权限、数据库、审计与备份；不能直接把浏览器 `localStorage` 版本公开上线。

## 推荐架构

```text
微信内 H5
   │ HTTPS
   ▼
Caddy / Nginx
   ├── /          React 静态文件
   └── /api/v1    Node.js API
                    │
                    ├── PostgreSQL（事件、成员、分数、审计）
                    └── COS（可选照片，私有桶）
```

首版一台2核2GB或2核4GB实例足够：

- `web`：Caddy 或 Nginx，负责 TLS、静态文件、反向代理和安全头；
- `api`：Node.js LTS 容器；
- `db`：正式扩展版使用 PostgreSQL 容器，数据卷挂载到实例磁盘；
- `backup`：每日加密备份到腾讯云 COS，保留7个日备份和4个周备份。

当前已实现的封闭试用部署使用 Node 24 内置 SQLite，并将数据库文件挂载到 Docker 命名卷。它适合严格只有一对用户、低并发的试用阶段；在接入照片、邀请登录、异地备份或第二对用户前，切换到 PostgreSQL。无论使用哪种数据库，都必须完成备份与恢复演练。

Redis、消息队列和 Kubernetes 都不是首版必要条件。只有两名用户时，少组件比“微服务完整”更可靠。

## 域名、HTTPS 与备案

中国大陆地域实例对公网提供网站服务，需要完成 ICP 备案。腾讯云文档明确说明大陆境内网站须先备案；域名解析到 Lighthouse 后，再配置 HTTPS。

两种选择：

1. **推荐长期方案：大陆地域 + 已备案域名**。微信内打开速度和稳定性更好。
2. **快速小范围试用：香港地域 + 正式 HTTPS 域名**。可减少备案等待，但大陆访问质量要实测，不能用它替代正式合规评估。

无论哪种方案，生产都必须 HTTPS。邀请链接、登录 Cookie 和照片不得通过明文 HTTP 传输。

## Docker Compose 服务边界

正式部署建议准备以下目录，不在当前纯前端阶段提前伪造后端：

```text
deploy/
├── compose.yaml
├── Caddyfile
├── api.env.example
├── backup/
└── scripts/
    ├── deploy.sh
    ├── backup.sh
    └── restore-check.sh
```

当前仓库已经提供 `compose.yaml`、`Dockerfile`、`server/Dockerfile`、`Caddyfile` 和 `.env.example`。容器只暴露 Caddy 的80/443端口；Node API 与 SQLite 卷只存在于 Docker 内部网络和主机持久卷中。

关键要求：

- 数据库不映射公网端口，只允许 Compose 内网访问。
- API 密钥和数据库密码只放服务器环境文件，不提交 Git。
- `/api/v1` 启用限流、请求体上限、CSRF 防护和结构化输入校验。
- Cookie 使用 `HttpOnly; Secure; SameSite=Lax`，登录态不放 localStorage。
- Caddy/Nginx 添加 HSTS、CSP、`X-Content-Type-Options` 和合理的 Referrer Policy。
- 事件正文不得出现在访问日志、异常上报或备份文件名里。

## 上线步骤

1. 购买 Lighthouse Linux 实例，配置仅开放 22、80、443 端口；SSH 进一步限制密钥登录。
2. 绑定域名并完成所需备案，配置 DNS。
3. 安装 Docker / Docker Compose，创建非 root 部署用户。
4. 部署前端、API 和 PostgreSQL，初始化两人配对站点。
5. 申请或自动签发 HTTPS 证书，验证自动续期。
6. 执行账号隔离、越权、重复计分、断网重试和备份恢复测试。
7. 先仅允许两人访问，稳定运行7天后再决定是否接入照片与微信分享能力。

在当前 SQLite 封闭试用版本中，第4步改为部署前端和 API 后，通过 `docker compose exec api node server/create-pair.mjs` 生成两条单次邀请链接。它们等同登录凭证，必须在受控 SSH 终端中生成并分别私下交给两人；不要复制进工单、群聊、部署日志或代码仓库。

## 发布门槛

- `npm run lint` 与 `npm run build` 通过。
- `/health` 同时验证 API 可用和数据库连接，不把数据库错误伪装成健康。
- 从公网 HTTPS、微信内 WebView、iPhone Safari、Android 微信各完成一次核心闭环。
- 验证未登录、丈夫越权审批、重复请求、过期邀请和旧会话全部被拒绝。
- 完成一次“从备份恢复到临时数据库”的演练。
- 保存部署前版本并提供可回滚镜像标签。

## 官方参考

- [腾讯云 Lighthouse：使用应用模板搭建 Docker 容器环境](https://cloud.tencent.com/document/product/1207/60423)
- [腾讯云 Lighthouse：创建及管理 Docker 容器](https://cloud.tencent.com/document/product/1207/60329/)
- [腾讯云 Lighthouse：添加域名](https://cloud.tencent.com/document/product/1207/81332)
- [腾讯云 Lighthouse：设置 HTTPS](https://cloud.tencent.com/document/product/1207/84358)

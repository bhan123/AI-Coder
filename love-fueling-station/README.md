# 爱意加油站

只属于两个人的行动与修复空间。当前仓库包含：

- 一套可交互的 React + Vite 移动端 H5 原型；
- 女方在首次初始化时设定0～100的起始温度；
- 首页、行动提交、审批/调分/驳回、直接扣分、账本和共同约定；
- 服务端行动账本：待确认行动、审批结果和直接扣分会持久化，并按最近30天的已生效记录计算当前温度；
- 账本记录不会因超过计分周期而删除；可在页面切换近1月、近3月或全部历史；
- 正式前端 PRD、视觉概念稿和腾讯云 Lighthouse 部署方案。

## 本地启动

```bash
npm install
npm run dev
```

生产构建：

```bash
npm run lint
npm run build
```

服务端权限测试：

```bash
npm run test:server
```

本地联调需另开一个终端启动 API，并为它设置至少32字符的临时会话密钥：

```powershell
$env:SESSION_SECRET = "只用于本地开发的长随机字符串"
$env:COOKIE_SECURE = "false"
npm run api:dev
```

创建一对一次性邀请链接：

```powershell
$env:APP_ORIGIN = "http://127.0.0.1:4173"
npm run create:pair
```

命令会在管理员终端输出一条女方链接和一条男方链接。每条链接只能使用一次；只把对应链接发送给本人，绝不把链接写入 Git、聊天截图或公共文档。

### 不部署的同 Wi-Fi 试用

适合先在家里用两台手机试用。电脑和两台手机必须在同一个可信 Wi-Fi；此模式没有 HTTPS，不要在公共网络、公司网络或长期运行。

1. 在电脑上用 `ipconfig` 找到当前 Wi-Fi 的 IPv4 地址，例如 `192.168.1.23`。
2. 终端 A 进入项目目录并启动 API：

```powershell
$env:SESSION_SECRET = "至少32位、仅本次试用使用的随机字符串"
$env:COOKIE_SECURE = "false"
npm run api:dev
```

3. 终端 B 启动 H5（`npm run dev` 已监听局域网地址）：

```powershell
npm run dev
```

4. 终端 C 生成邀请。把示例 IP 替换为第 1 步的电脑 IP：

```powershell
$env:APP_ORIGIN = "http://192.168.1.23:5173"
npm run create:pair
```

5. 把终端 C 输出的女方链接和男方链接分别私发给对应手机；手机用微信打开即可。若 Windows 弹出防火墙提示，允许 Node.js 通过“专用网络”。试用结束后关闭两个服务终端；本机的 `data/love-fueling-station.sqlite` 会保留试用记录。

## Lighthouse 封闭试用部署

复制 `.env.example` 为服务器上的 `.env`，填入已备案域名和至少32字符的随机 `SESSION_SECRET`，然后执行：

```bash
docker compose up -d --build
```

容器组合只公开 Caddy 的80/443端口；API与SQLite数据卷不暴露公网。首次封闭试用适合一对伴侣使用，部署、备份和正式账号接入说明见 [Lighthouse 部署方案](./docs/tencent-lighthouse-deployment.md)。

容器启动后，在 Lighthouse 的受控 SSH 终端执行一次 `docker compose exec api node server/create-pair.mjs` 生成两条邀请链接。它们属于登录凭证，按对应角色私下发送，使用后自动失效。

### 无域名临时 HTTPS 试用

`compose.tunnel.yaml` 通过 Cloudflare Quick Tunnel 提供临时 HTTPS 地址：服务仅监听服务器回环地址，数据库与 API 不对公网开放。该地址会在隧道重建后变化，且不承诺稳定性；仅用于备案期间的短期双人试用。部署人员应在受控 SSH 终端从 `tunnel` 容器日志读取临时站点地址，再以该地址设置 `APP_ORIGIN` 并运行 `server/create-pair.mjs`。邀请链接等同登录凭证，不能复制到仓库、公共日志或工单。

## 当前边界

这是封闭试用版。一次性邀请、女方专属初始化、行动提交、女方审批/调分/驳回、女方直接扣分、男方提交修复、女方确认修复和审计记录均已接入服务端；浏览器不再把积分或账本当作数据源。行动照片入口目前为保证微信内使用稳定而暂不开放；微信服务通知、低分提醒推送、双方共同修改初始温度与正式账号恢复流程仍待完成。

产品与交互细节见 [前端 PRD](./docs/frontend-prd-v0.1.md)，部署细节见 [Lighthouse 部署方案](./docs/tencent-lighthouse-deployment.md)。

# CloudBase 上线清单

本项目采用微信小程序原生 CloudBase 调用：小程序不通过 `wx.request` 调自建 API，不需要自定义域名或备案。所有业务写入只允许经过 `relationship-api` 云函数；客户端不应被授予直接读写关系数据的权限。

## 你需要在自己的账号中完成

1. 注册微信小程序并取得 AppID。内测可以是个人主体；商业支付版请使用公司或个体工商户主体的新 AppID。
2. 在微信开发者工具中导入本项目，以该 AppID 开启「云开发」，创建一个 `test` 环境。获得环境 ID（例如 `xxx-123456`）。环境 ID 不是密钥。
3. 将 AppID 填入根目录 `project.config.json`，将环境 ID 填入 `src/config/cloudbase.ts` 的 `cloudEnvironmentId`。
4. 在微信开发者工具的 `cloudfunctions/relationship-api`、`cloudfunctions/privacy-cleanup`、`cloudfunctions/notification-dispatch` 和 `cloudfunctions/operations-api` 上分别选择「上传并部署：云端安装依赖」。各目录的 `package-lock.json` 必须随源码上传，以锁定线上传递依赖；不要上传 `node_modules`，更不要提供 AppSecret。
5. 为 `privacy-cleanup` 配置每小时执行一次的定时触发器，并先用一条虚构删除请求验证它会返回 `processed` 且 `failed` 为空。为 `notification-dispatch` 配置每 5 分钟一次的定时触发器。对删除函数的 `ok: false`、非空 `failed`、`requiresAttention: true` 或 `backlogAfter.total > 0`，以及通知函数积压/持续重试配置告警；当积压持续两次触发时，提升 `PRIVACY_CLEANUP_BATCH_SIZE`（默认20，最大100）或排查失败请求。未部署删除触发器时，删除承诺不会自动兑现，禁止收集真实内容。
6. 在云开发数据库中将下列集合的权限均设为仅云函数可访问：`users`、`user_identities`、`user_pairing_locks`、`privacy_consents`、`couples`、`memberships`、`pair_invites`、`relationship_records`、`couple_settings`、`audit_events`、`idempotency_keys`、`rate_limits`、`privacy_requests`、`privacy_deletion_receipts`、`data_backups`、`notification_outbox`、`subscription_grants`、`media_upload_tickets`。推荐安全规则：

```json
{ "read": false, "write": false }
```

同时建立以下组合索引：

> 除数据库自动创建的 `_id` 主键索引，以及可选择设为唯一的 `pair_invites(codeHash)` 外，下面其余业务索引都必须创建为**非唯一索引**。索引名称只是标签，必须在对应集合中逐项核对字段；不要把集合名当成索引字段，也不要把某个集合的索引建到其他集合中。误建的唯一索引会让缺少该字段的多条文档都以 `null` 冲突，导致正常业务写入报 `DuplicateKey`。

- `memberships(userId, status)`；
- `pair_invites(codeHash)` 与 `pair_invites(creatorUserId, status)`；
- `relationship_records(coupleId, createdAt desc, _id desc)`；
- `user_identities(userId, createdAt desc, _id desc)`、`privacy_consents(userId, agreedAt desc, _id desc)`、`memberships(userId, createdAt desc, _id desc)`、`pair_invites(creatorUserId, createdAt desc, _id desc)`；
- `privacy_requests(userId, createdAt desc, _id desc)`、`privacy_requests(requestedBy, createdAt desc, _id desc)`、`audit_events(actorUserId, createdAt desc, _id desc)`；
- `privacy_requests(coupleId, status)`；
- `privacy_requests(status, executeAfter)`、`privacy_requests(status, backupDeleteAfter)` 与 `privacy_requests(status, expiresAt)`；
- `rate_limits(expiresAt)`。
- `notification_outbox(status, createdAt)`、`notification_outbox(status, retryAfter)`、`notification_outbox(status, sendingAt)` 与 `subscription_grants(userId, templateId, remainingQuota)`；
- `media_upload_tickets(userId, status)`、`media_upload_tickets(coupleId, status)` 与 `media_upload_tickets(status, expiresAt)`。

没有这些索引时，真实数据量增长后查询可能变慢或直接被 CloudBase 拒绝。

云函数拥有服务端权限，仍可正常写入；客户端被拒绝直接查询，避免通过猜测 `coupleId` 越权。

7. 在腾讯云访问管理（CAM）中使用个人账号和最小权限角色，禁止共享管理员账号；开启能覆盖 CloudBase/数据库控制台操作的云审计日志并设置留存和告警。应用本身没有管理员读取关系内容的接口，但控制台访问无法由小程序代码自行拦截或完整审计。
8. `relationship-api/config.json` 已声明 `security.msgSecCheck` 权限。上传云函数后确认该 OpenAPI 可调用；当前实现为安全失败关闭，权限未生效、接口异常或内容未通过时都不会落库。用虚构文本完成一次通过与一次拦截测试，禁止用真实敏感内容试探审核边界。
9. 订阅提醒默认关闭。先在 `relationship-api` 设置环境变量 `ENABLE_SUBSCRIPTIONS=true`，再在公众平台选定消息模板：把模板 ID 同时填入 `src/config/notifications.ts` 与 `notification-dispatch` 的环境变量 `SUBSCRIBE_TEMPLATE_ID`；按实际模板字段修改 `SUBSCRIBE_EVENT_FIELD`、`SUBSCRIBE_TIME_FIELD`。`notification-dispatch/config.json` 已声明 OpenAPI 权限。提醒必须保持中性，不得携带行动、感受或回应正文。派发函数默认最多重试 3 次，超过次数、发送状态不确定或 30 天前的终态通知都应在控制台告警与清理任务中可见。
10. 扫码邀请要求 CloudBase 环境已关联当前小程序 AppID；`relationship-api/config.json` 已声明 `wxacode.getUnlimited`。先在体验版生成并扫码，确认 `scene` 参数能落到配对页后才向用户开放。
11. 照片上传默认关闭。只有在已完成存储权限（客户端不得列目录或任意读取）、微信隐私保护指引的相机/相册选择披露、附件删除演练及真机内容安全策略验证后，才可将 `src/config/media.ts` 的 `recordMediaUploadsEnabled` 与云函数环境变量 `ENABLE_MEDIA_UPLOADS` 同时改为 `true`。上传文件必须位于云函数签发的 `relationship-media/<couple>/<ticket>` 临时路径；不得公开存储桶。
12. 最小化运营指标页由 `operations-api` 保护：仅将需访问者的 OpenID 填入该函数环境变量 `ADMIN_OPENIDS`，不要把 OpenID 写入前端。该页只应展示计数和积压，不应新增读取正文或用户列表的接口。
13. 在微信公众平台完成《小程序用户隐私保护指引》，其数据类型、用途、保存期限、第三方处理、导出和删除渠道必须与 `pages/privacy` 的实际能力一致。`PRIVACY_NOTICE_VERSION` 升级后，已配对用户会被阻止加载记录，直到在隐私页重新确认；版本号必须与云函数常量同步更新。
14. 在小程序后台把自己和首批试用者设为开发/体验成员，上传体验版后用真机测试：创建邀请 → 分享/扫码 → 另一微信接受 → 双方各写一条记录 → 对方回应 → 丢包后用同一 `operationId` 重试 → 导出 JSON 与分段导出 → 退出后再次导出并确认没有伴侣正文 → 发起删除 → 执行清理函数 → 全集合检索确认已无原始 `userId`、本人文本和附件文件。

## 已保存的数据

- `relationship_records`：行动、感受、回应、共同约定及其状态变化；记录不会因状态变化而被删除。
- `couple_settings`：当前爱意分数及初始化时间；行动审批、感受直扣和双方确认的手动调分均会留下对应的原始记录。
- `audit_events`：配对、写入、回应、确认、退出等关键动作。
- `users` 与 `user_identities`：内部 `userId` 与当前 AppID/OpenID 的映射。业务记录不以 OpenID 为主键，方便未来迁移至公司主体新 AppID。
- `idempotency_keys`：失败重试使用的短期操作凭证，7天后由清理任务删除。
- `rate_limits`：服务端固定时间窗计数；过期计数由清理任务删除。业务写入默认每10分钟最多60次，记录/回应和约定使用更低的独立阈值，个人数据导出每小时最多3次。
- `privacy_requests`：待执行的本人/共同空间删除请求；业务主库清理后会去标识化，应用备份阶段完成后删除。
- `privacy_deletion_receipts`：不含用户或共同空间原始 ID 的最小化删除回执。
- `data_backups`：仅供未来应用自行生成备份时登记；清理任务按删除请求删除关联副本。当前代码不会主动生成内容备份。

历史页每次读取 100 条，并使用 `(createdAt, _id)` 复合游标继续加载；这是加载策略，不是保留上限。云端不因页面筛选或分页而删除历史记录。

“导出我的原始数据”是个人导出：仅包含本人资料、本人创建的记录，以及本人写在他人记录中的回应/约定决定；不会包含伴侣正文或伴侣对本人记录的回应。即使 membership 已撤销也遵循这一范围。完整共同空间导出尚未开放，未来如实现必须建立独立申请并要求双方分别确认。

导出从服务端记录的 `snapshotAt` 起点开始，以时间戳和 `_id` 的复合游标读取，避免 `skip(offset)` 在并发新增时造成重复或遗漏。它不是数据库事务快照：极少数恰在导出窗口内被更新的既有字段，可能反映导出前或导出中的状态。当前版本设有 1000 行与 512 KiB 上限，超过即拒绝并提示分段导出；在未设计完加密文件、下载鉴权、保存期限及删除联动前，禁止通过云存储静默扩展为完整文件导出。

## 删除语义

- 本人删除：立即关闭当前共同空间并停止共享；到达 `executeAfter` 后删除本人的身份映射、资料、邀请、幂等凭证、本人写入的关系记录和本人操作审计，同时字段级擦除本人留在对方记录中的回应/确认文本与跨集合身份引用。该清理会遍历已撤销的历史 membership，因此退出后的前成员仍可完成本人删除。
- 共同空间删除：申请7天内有效，必须由另一位有效成员确认；确认后立即停止共享，到达 `executeAfter` 后删除该空间的记录、约定设置、成员关系和业务审计。任一方先退出会自动取消并匿名化待确认申请；未确认的过期申请由清理任务删除。
- 应用备份删除：到达 `backupDeleteAfter` 后删除 `data_backups` 中与请求关联的应用自建副本，再写入不含原始身份的最小回执。
- CloudBase 平台自身的灾备副本生命周期不由本仓库代码控制。正式运营主体必须在腾讯云合同与控制台能力范围内核实其删除周期，并在正式隐私政策中如实写明，不能把“应用备份30天”扩张解释为所有平台灾备均已删除。

## 上线阻断项

以下任一项未完成时，只允许虚构测试数据：

- `privacy-cleanup` 未部署或没有定时触发器；
- 任一业务集合允许小程序客户端直接读写；
- 没有可核验的 CAM 最小权限和云审计；
- 微信隐私保护指引未配置或与产品页面不一致；
- 没有实际运营主体、联系/投诉方式和完整隐私政策；
- 没有完成两账号并发配对、重复提交、并发回应/确认、导出和删除的真机验收。
- 内容安全 OpenAPI 未实测成功或服务端频控集合/索引未配置。
- `privacy-cleanup` 返回积压或失败却没有告警和处理预案；
- 未完成线上依赖扫描前，不得声称依赖“无漏洞”。线上 `npm audit` 会向 npm 服务发送依赖元数据，需取得运营方明确授权后再在受控 CI 中执行并留存结果。

## 生产建议

- 个人主体仅作试用。公司主体正式版使用新的 CloudBase `prod` 环境，先导出并校验数据后再导入。
- 如需备份，必须登记备份位置、加密方式、负责人、保存期限和关联删除请求；演练恢复与按期删除。不要建立无法定位或无法清理的离线副本。
- 正式提审前完成隐私保护指引，清楚告知记录内容、保存目的、导出/删除渠道和共同空间退出规则。
- 目前邀请以一次性文本码实现。正式版可扩展为带临时参数的小程序码，但扫码后仍必须由接收方点击确认。

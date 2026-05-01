# FreezeHost 续期多账号版

> ⭐ 觉得有用？给个 Star 支持一下！
>
> 注册地址：[https://free.freezehost.pro](https://free.freezehost.pro)

自动续期 [FreezeHost](https://free.freezehost.pro) 免费服务器，防止到期被删除。

通过 GitHub Actions 定时运行，使用 Playwright 模拟浏览器操作完成续期，最多支持 5 个 Discord 账号，支持 Telegram 通知、WARP 代理、智能调度。

## 功能

- 自动登录 Discord OAuth 并续期所有服务器
- 支持最多 5 个 Discord Token 分别续期，各账号独立 Cron 计划
- 自动处理站点宕机重试（最多 3 次）
- 续期后自动计算下次运行时间（到期前 2 天），并更新 Workflow 中的 Cron 表达式
- 通过 WARP 代理确保网络连通性
- Telegram 机器人推送续期结果（含合并截图）
- 仅需配置 Secrets 即可一键部署

## 配置 Secrets

在仓库 `Settings → Secrets and variables → Actions` 中添加以下密钥：

| Secret 名称 | 必填 | 说明 |
|---|---|---|
| `FREEZEHOST_DISCORD_TOKEN_1` | ✅ | 第 1 个 Discord 账号 Token |
| `FREEZEHOST_DISCORD_TOKEN_2` | ❌ | 第 2 个 Discord 账号 Token（可选） |
| `FREEZEHOST_DISCORD_TOKEN_3` | ❌ | 第 3 个 Discord 账号 Token（可选） |
| `FREEZEHOST_DISCORD_TOKEN_4` | ❌ | 第 4 个 Discord 账号 Token（可选） |
| `FREEZEHOST_DISCORD_TOKEN_5` | ❌ | 第 5 个 Discord 账号 Token（可选） |
| `REPO_TOKEN` | ✅ | 具有 `repo` 和 `workflow` 权限的 Personal Access Token，用于自动更新 Cron |
| `TG_BOT_TOKEN` | ❌ | Telegram Bot Token，用于推送通知 |
| `TG_CHAT_ID` | ❌ | Telegram 接收消息的 Chat ID |

### 获取 Discord Token

1. 在浏览器中登录 [FreezeHost](https://free.freezehost.pro)（使用 Discord 登录）
2. 打开开发者工具 (F12) → Application → Local Storage → 查找 `token` 字段（引号内的字符串）
3. 复制该值作为 `FREEZEHOST_DISCORD_TOKEN_*`

### 获取 REPO_TOKEN

1. 访问 [GitHub Tokens](https://github.com/settings/tokens) → Generate new token (classic)
2. 勾选 `repo` (全部) 和 `workflow` 权限
3. 生成并复制 Token

### Telegram 通知（可选）

1. 通过 [@BotFather](https://t.me/BotFather) 创建 Bot，获取 `TG_BOT_TOKEN`
2. 获取你的 Chat ID（可发送消息给 bot 后访问 `https://api.telegram.org/bot<TOKEN>/getUpdates`）
3. 填入对应 Secret

## 使用

1. Fork 本仓库
2. 启用 Actions（如果默认未启用）
3. 添加上述 Secrets
4. 脚本会自动按 Cron 运行（默认已配置 5 个独立 Cron，对应 5 个 Token）
5. 也可在 Actions 页面手动触发 (`workflow_dispatch`)，选择 Token 编号执行

首次运行后，Workflow 会自动根据剩余天数调整对应 Token 的 Cron 时间，下次运行将精确到到期前 2 天。

## 工作原理

1. **定时触发**：每个 Token 拥有独立的 Cron 行，避免冲突（UTC 1-5 点各一个）
2. **确定 Token**：根据触发小时或手动选择，匹配对应 Secret
3. **环境准备**：拉取仓库、安装 Python 及 Playwright，启动 WARP 代理，修复 DNS
4. **登录续期**：Python 脚本打开无头浏览器，通过 Discord OAuth 登录，发现所有服务器，逐一检查剩余时间并执行续期
5. **结果提取**：从续期日志中提取剩余天数最小值
6. **智能调度**：若剩余天数 > 2 天，设置下次运行时间为“剩余天数 - 2”天后；否则 12 小时后重试
7. **自动提交**：使用 `REPO_TOKEN` 修改 Workflow 文件中对应 Cron 行并推送
8. **通知**：通过 Telegram 发送续期结果截图（所有服务器合并为一张图片）

## 注意事项

- 请确保至少配置一个 `FREEZEHOST_DISCORD_TOKEN_1`，否则无法续期
- `REPO_TOKEN` 必须具有 `workflow` 权限，否则无法自动更新 Cron 表达式
- 如果某个 Token 下无服务器，脚本会发送无服务器通知并跳过
- 脚本内置站点宕机检测与重试机制（最多 3 次），若持续宕机会在 Telegram 通知
- 截图和日志中的敏感信息（Token、邮箱、服务器 ID 等）已做脱敏处理
- 若需更多 Token，可参考现有 Workflow 结构扩展

---

**⚠️ 免责声明**：本脚本仅供学习交流使用，使用者需遵守 [FreezeHost](https://free.freezehost.pro) 的服务条款。因使用本脚本造成的任何问题，作者不承担任何责任。

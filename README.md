# Notion Private Writer

一个用于把 Markdown 笔记批量写入 Notion 的 Codex Skill。它适合把论文解读、长文档总结、课程笔记、项目复盘等内容，按“一个 Markdown 文件对应一个 Notion 子页面”的方式导入到指定 Notion 页面下。

这个仓库来自一次真实任务：把多篇 SMA 机器人相关论文的中文深度解读写入 Notion，并要求每篇论文单独成页，最后再生成总览表。过程中发现 Notion 页面粘贴超长内容、浏览器自动化写入、多页面组织都容易失败，于是整理成了这个可复用的 Skill。

## 它解决什么问题

很多时候，我们希望 Codex 或其他 AI 工具生成大量结构化笔记，然后直接沉淀到 Notion 里，例如：

- 一批论文阅读笔记，每篇论文一个页面；
- 多个会议纪要、访谈记录或项目复盘；
- 长篇研究报告拆成多个章节页；
- AI 生成的 Markdown 文件夹批量导入 Notion；
- 避免手动复制粘贴导致格式丢失、页面过长、浏览器卡死。

Notion 官方 API 适合数据库和标准集成，但在用户没有提前创建 integration token、只是在本机已经登录 Notion 的情况下，临时写入私人页面会比较麻烦。本 Skill 使用用户本机已有的 Notion 登录态，通过 Notion Web 私有接口完成导入。

## 主要能力

- 读取一个文件夹下的 `.md` 文件；
- 每个 Markdown 文件创建为一个 Notion 子页面；
- 自动从一级标题 `#` 提取页面标题；
- 支持给导入页面添加统一标题前缀；
- 支持导入前 dry-run，先检查将要写入的内容；
- 支持清理父页面下的错误子页面引用；
- 支持把常见 Markdown 结构转换成 Notion 块；
- 使用本机 Notion 登录 Cookie，不需要手动复制 token；
- 尽量避免在终端输出敏感 Cookie、token 或解密后的凭据。

## 支持的 Markdown 映射

当前脚本会把常见 Markdown 结构转换为 Notion 块：

| Markdown | Notion 块 |
| --- | --- |
| `# 一级标题` | 页面标题 |
| `## 二级标题` | `sub_header` |
| `### 三级标题` 及更深标题 | `sub_sub_header` |
| 普通段落 | `text` |
| `-` / `*` 列表 | `bulleted_list` |
| `1.` 有序列表 | `numbered_list` |
| `>` 引用 | `quote` |
| `$$ ... $$` | `equation` |
| Markdown 表格 | `table` + `table_row` |
| 代码块 | `code` |

其中公式块会以 Notion equation 形式写入，适合论文笔记里的 LaTeX 公式。

## 环境要求

当前版本主要面向 macOS，因为脚本会读取 macOS 上 Notion Desktop 或 Codex 内置浏览器的 Cookie 数据库，并通过 Keychain 解密 Cookie。

建议环境：

- macOS；
- Python 3；
- 已安装并登录 Notion Desktop，或在 Codex 内置浏览器里登录过 Notion；
- 系统可用 `security`、`openssl`、`sqlite3` 等 macOS 常见工具；
- 目标 Notion 页面必须是当前登录账号有权限编辑的页面。

脚本本身只使用 Python 标准库，不需要额外安装 Python 包。

## 安装方式

如果你想把它作为 Codex Skill 使用，可以克隆到本机 Codex skills 目录：

```bash
mkdir -p ~/.codex/skills
git clone https://github.com/KOU-ROU/notion-private-writer.git ~/.codex/skills/notion-private-writer
```

然后重启 Codex，或者开启一个新的 Codex 会话。之后当你要求 Codex “把 Markdown 笔记写入 Notion”“给某个 Notion 页面创建多个子页面”“批量导入论文解读”等场景时，这个 Skill 会被用来指导操作。

你也可以不作为 Codex Skill 使用，直接运行脚本：

```bash
git clone https://github.com/KOU-ROU/notion-private-writer.git
cd notion-private-writer
python3 scripts/notion_md_import.py --help
```

## 快速开始

准备一个 Markdown 文件夹：

```text
notes/
├── 00-总览.md
├── 01-论文A.md
├── 02-论文B.md
└── 03-论文C.md
```

每个文件建议用一级标题作为 Notion 页面标题：

```markdown
# 论文A：标题

## 1. 研究问题

这里写论文解读内容。

## 2. 方法

这里写方法分析。
```

先 dry-run，确认页面 ID 和文件列表能被正常识别：

```bash
python3 scripts/notion_md_import.py \
  --parent-page-id "https://www.notion.so/your-page-id" \
  --notes-dir ./notes \
  --dry-run
```

确认无误后正式写入：

```bash
python3 scripts/notion_md_import.py \
  --parent-page-id "https://www.notion.so/your-page-id" \
  --notes-dir ./notes
```

如果希望所有页面标题前面带一个统一前缀：

```bash
python3 scripts/notion_md_import.py \
  --parent-page-id "https://www.notion.so/your-page-id" \
  --notes-dir ./notes \
  --page-title-prefix "论文阅读 | "
```

## 参数说明

```bash
python3 scripts/notion_md_import.py \
  --parent-page-id <Notion父页面URL或页面ID> \
  --notes-dir <Markdown文件夹>
```

常用参数：

| 参数 | 作用 |
| --- | --- |
| `--parent-page-id` | 目标 Notion 父页面 URL 或页面 ID |
| `--notes-dir` | 存放 `.md` 文件的文件夹 |
| `--cookie-profile notion-desktop` | 默认值，读取 Notion Desktop 登录态 |
| `--cookie-profile codex-iab` | 读取 Codex 内置浏览器的 Notion 登录态 |
| `--page-title-prefix` | 给每个新页面标题增加前缀 |
| `--clean-parent` | 导入后只保留本次创建的子页面引用，谨慎使用 |
| `--remove-child-id` | 从父页面 content 列表移除已知错误子页面 ID |
| `--dry-run` | 只检查和预览，不写入 Notion |

## 在 Codex 里怎么用

安装后，你可以直接对 Codex 说类似这样的话：

```text
请把 /path/to/notes 里面的 Markdown 笔记导入到这个 Notion 页面：
https://www.notion.so/xxxx
每个 Markdown 文件创建成一个单独子页面。
```

或者：

```text
我已经登录 Notion。请把这些论文解读写进 Notion，每篇论文一个页面，并最后创建总览页。
```

Codex 会根据 Skill 的说明：

1. 生成或整理 Markdown 文件；
2. 解析 Notion 父页面 ID；
3. 读取本机 Notion 登录态；
4. 用脚本创建子页面和内容块；
5. 验证父页面是否出现了对应子页面；
6. 必要时清理失败的临时条目。

## 安全说明

这个项目使用 Notion 的私有 Web API，不是 Notion 官方公开 API。使用前请理解以下边界：

- 只在你自己的电脑和你有权限编辑的 Notion 工作区中使用；
- 不要把 Cookie、token、Keychain 输出或调试日志发给别人；
- 脚本会在内存中解密 Cookie，但设计上不会打印 Cookie 值；
- Notion 私有 API 可能随时变化，未来可能需要维护；
- 大批量写入前建议先在测试页面 dry-run 和小规模试写；
- `--clean-parent` 会修改父页面的子块列表，使用前要确认目标页面没有重要内容。

如果你有正式的 Notion integration token，并且任务可以通过官方 API 完成，优先使用 Notion 官方 API。这个 Skill 更适合“用户本机已经登录 Notion，但没有提前配置 integration”的临时写入场景。

## 常见问题

### 1. 提示找不到 `token_v2`

说明选定的 Cookie profile 没有登录 Notion。请确认：

- Notion Desktop 已经登录；
- 或者改用 `--cookie-profile codex-iab`，并确认 Codex 内置浏览器里登录过 Notion；
- 登录后重试。

### 2. Notion 返回 `MemcachedCrossCellError`

通常是请求缺少 `spaceId` 或请求被路由到了错误的 Notion cell。这个 Skill 的脚本会先解析父页面所属的 `space_id`，并在后续请求中带上 `x-notion-space-id`。

### 3. 子页面链接出现了，但页面内容为空

这通常和 Notion 私有 API 的 transaction 格式有关。脚本使用的是已经验证过的 `saveTransactions` flat operation 格式，而不是容易失败的 pointer 格式。如果你修改脚本，请先用一个最小 Markdown 页面测试。

### 4. 页面太长或导入失败怎么办

建议把内容拆成多个 Markdown 文件，或者把单篇超长文档拆成章节页。Notion 可以接受较多 block，但小页面更容易验证、恢复和维护。

### 5. Windows 或 Linux 能用吗

当前脚本主要针对 macOS，因为 Cookie 解密依赖 macOS Keychain 和本地 Notion/Codex Cookie 路径。Windows/Linux 需要单独适配 Cookie 存储路径和解密方式。

## 项目结构

```text
notion-private-writer/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   └── notion-private-api-notes.md
└── scripts/
    └── notion_md_import.py
```

- `SKILL.md`：Codex Skill 的核心说明；
- `agents/openai.yaml`：Skill 在 Codex 界面中的展示信息；
- `references/notion-private-api-notes.md`：Notion 私有 API 排错和经验记录；
- `scripts/notion_md_import.py`：Markdown 到 Notion 子页面的实际导入脚本。

## 适合的使用场景

这个 Skill 特别适合研究和知识管理工作流：

- 批量论文阅读笔记；
- AI 生成的中文文献综述；
- 长课程资料拆页导入；
- 项目资料库初始化；
- 把本地 Markdown 知识库迁移到 Notion；
- 给团队创建结构化 Notion 页面草稿。

例如，论文阅读可以组织成：

```text
SMA论文阅读/
├── 00-总览表.md
├── 01-论文1深度解读.md
├── 02-论文2深度解读.md
└── ...
```

导入后，Notion 父页面下会出现一个总览页和多个论文解读子页面，阅读和检索都会比一个超长页面更舒服。

## 贡献与维护

欢迎基于这个仓库继续扩展：

- 增强 Markdown 解析；
- 支持更多 Notion block 类型；
- 增加 Windows/Linux Cookie profile；
- 增加更完善的失败恢复；
- 增加官方 API 模式；
- 改进大规模导入的分批 transaction。

如果你在使用中遇到 Notion 私有 API 报错，请尽量记录错误类型、触发场景和是否能在最小 Markdown 文件中复现，但不要公开任何 Cookie、token 或私人页面内容。

## 免责声明

本项目是面向个人自动化和学习研究的工具。它不是 Notion 官方产品，也不保证兼容 Notion 未来的私有接口变化。请在理解风险的前提下使用，并优先保护自己的账户、数据和工作区安全。

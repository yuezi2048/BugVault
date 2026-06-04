<div align="center">

# BugVault

**Bug Experience Vault & Intelligent Retrieval System**

*LLM に永続的なセッション間デバッグ記憶を提供するローカルファースト MCP サーバー。*

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-2024--11--05-purple.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

[English](README.md) | [中文](README.zh.md) | [日本語](README.ja.md)

</div>

---

## 概要

BugVault は **ローカルファーストの MCP サーバー** であり、LLM（意思決定 Agent）とペアを組む専用「記憶 Agent」として機能し、**2-Agent 協調デバッグシステム** を構成します。

- **意思決定 Agent**（Claude / 任意の LLM）：バグの診断、修正案の策定、保存・振り返りの判断
- **記憶 Agent**（BugVault）：意味検索、解決策の永続化、RAG 品質評価、予防ルールの書き込み

すべてのデータは **100% ローカル** に保存 — クラウドなし、API 費用なし、データ漏洩なし。

### Agent 自己進化サイクル

```
 トラブルシューティング ──→ 解決 ──→ 振り返り ──→ 二度と繰り返さない
    (検索)              (保存)       (振り返り)
       ↑                                    │
       └──────── 知識ベース ────────────────┘
              (LanceDB + .md + CLAUDE.md)
```

サイクルを完了するたびに Agent は賢くなります — 過去の解決策を検索可能になり、予防ルールが同じミスの再発を防ぎます。

### 3 つのツール

BugVault はバグ修正ライフサイクル全体をカバーする 3 つの MCP ツールを公開し、**各ツールは単一責任** を持ちます：

| ツール | 責任 | オプション |
|--------|------|-----------|
| `retrieve_bug_experience` | 🛠️ トラブル中 — 意味検索 + 精密再ランク + RAG 品質評価 | 評価はオプション |
| `save_bug_experience` | 💾 解決後 — Markdown 即時保存 + バックグラウンド非同期ベクトル登録 | 非同期はオプション |
| `reflect_and_prevent_error` | 🧠 振り返り — 根本原因の分類 + CLAUDE.md への予防ルール書き込み | ✅ オプション |

### 主な機能

### v1.1 新機能

- **🎯 ハイブリッド検索** — ベクトル + FTS 全文検索の二系統を RRF(k=60) で融合、詳細は [v1.1 アーキテクチャ](docs/refer/02設計/04.v1.1-architecture.md) 参照
- **⚡ Cross-Encoder 再ランク** — 軽量 ONNX モデルで 2 次スコアリング、[ADR 選定記錄](docs/refer/02設計/adr-cross-encoder-vs-colbert.md) 参照
- **🧪 Claim-Level 評価** — CoT 思考連鎖で声明抽出 → 逐一検証 → `claims_analysis[]` 出力、[評価戦略](docs/refer/02設計/04.v1.1-architecture.md#二評価リンク戦略パターン--二重フォールバック) 参照
- **🛡️ 二重フォールバック** — クォータ制限 + 例外捕捉、LLM 解析失敗時もメインスレッドをブロックしない
- **🔍 メタデータ事前フィルター** — `target_tech_stack` + `target_project_name`、大文字小文字を区別せず SQL インジェクション対策済み
- **📊 Token 統計** — 評価ごとに `prompt_tokens` / `completion_tokens` / `total_tokens` を返却
- **🧹 DB メンテナンス** — `drop_table()` + 並行バッチリビルド、65 件 0.6 秒
- **🔒 パス安全性** — 全局 `.expanduser().resolve()` + `mkdir()` 事前作成

### v1.0 継続機能

- **意味検索** — 自然言語で過去のバグを検索
- **重複排除 & Upsert** — MD5 主キー + `merge_insert`、重複ゼロ
- **並行処理安全性** — `threading.Lock` 保護
- **Agent 自己進化** — CLAUDE.md に予防ルール書き込み
- **純粋ローカル** — `~/.bugvault/`、ネットワーク不要
- **MCP ネイティブ** — Claude Desktop、Claude Code など対応

---

## クイックスタート

### 前提条件

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（パッケージマネージャー）

### インストール

```bash
git clone https://github.com/yourusername/bugvault.git
cd bugvault
uv sync

#（オプション）RAG 評価用 LLM の設定
cp .env.example .env
# .env 編集 — BUGVAULT_ENABLE_RAG_EVAL=true と BUGVAULT_EVAL_LLM_API_KEY

# 検証（70+ テスト）
uv run pytest -v

#（オプション）アーカイブから再構築
uv run python scripts/rebuild_index.py --skip-clear
```

### MCP サーバーの起動

MCP クライアント（Claude Desktop、Claude Code、Cursor 等）の設定に以下を追加：

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

詳細は [デプロイメントガイド](docs/refer/分析/05.交付形式.md) を参照。

---

## アーキテクチャ：2-Agent 協調

```
┌─────────────────────────────────────────────────────────────────┐
│                  意思決定 Agent (Claude)                         │
│                                                                  │
│  1. ユーザーがバグを報告                                           │
│  2. Agent が retrieve_bug_experience を呼び出す ←──────────┐    │
│     → 過去の解決策 + RAG 信頼度スコアを取得                  │    │
│  3. Agent が診断 + 修正                                     │    │
│  4. Agent が save_bug_experience を呼び出す ────────────────┘    │
│     → MD 即時アーカイブ + 非同期ベクトルインデックス            │    │
│  5. Agent が reflect_and_prevent_error を呼び出す               │    │
│     → 予防ルールが CLAUDE.md に書き込まれる                      │    │
│  6. 次回セッション：CLAUDE.md 自動ロード → 同じミスをしない    │    │
└──────────────────┬────────────────────────────────────────────┘
                   │ JSON-RPC via stdio (MCP)
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    記憶 Agent (BugVault)                         │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  単一責任の 3 ツール                                     │    │
│  │                                                         │    │
│  │  🛠️ 検索 ────  🧠 保存 ────  📝 振り返り              │    │
│  │  (独立 ANN  (MD 同期 +    (根本原因分類 +              │    │
│  │   + 再ランク 非同期ベクトル) CLAUDE.md 書き込み)        │    │
│  │   + RAG 評価)                                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ LanceDB  │  │fastembed │  │ RAG LLM │  │ アーカイブ│       │
│  │ (ベクトル)│  │ (ONNX)   │  │ (判定)   │  │ (.md)    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

### 明確な境界

| レイヤー | 責任 | 決してしないこと |
|---------|------|----------------|
| **意思決定 Agent**（Claude） | 診断、修正、保存/振り返りの判断 | ❌ DB を直接操作 |
| **記憶 Agent**（BugVault） | 検索、永続化、評価、ルール書き込み | ❌ バグ修正や意思決定 |
| **RAG 評価** | 信頼度データを返すのみ | ❌ Claude の返信を変更 |

---

## 3 ツール詳細

### 🛠️ `retrieve_bug_experience` — 独立検索 + 評価

Agent がバグに遭遇したとき（またはユーザーが過去のバグについて質問したとき）、このツールを呼び出します。**全処理が BugVault 側で独立して実行され**、Claude との複雑な通信はありません：

```
1. クエリ埋め込み → 2. ANN 検索 → 3. ハイブリッド再ランク + 意味閾値 → 4. [オプション] RAG 評価
```

### 💾 `save_bug_experience` — 2 パス非同期保存

Agent がバグを修正した後、**試行パス** と **最終結果** を保存します：

| パス | 速度 | 内容 |
|------|------|------|
| **SYNC**（executor スレッド） | **ミリ秒** | Pydantic 検証 → MD5 record_id → .md アーカイブ書き込み → "saved successfully" |
| **ASYNC**（fire-and-forget） | ~100ms | ONNX 埋め込み → LanceDB `merge_insert`（`record_id` で自動重複排除） |

### 🧠 `reflect_and_prevent_error` — Agent 自己進化

振り返りツールが BugVault を **使うほど賢く** します。Agent が根本原因を能動的に分類：

| カテゴリ | 意味 | 例 |
|---------|------|-----|
| `understanding_bias` | ユーザーの暗黙的な意図の誤解 | 「顧客が環境変数の設定を明示しなかった」 |
| `code_logic_error` | コードロジックの不備 | 「.get() の None 返却をチェックし忘れた」 |
| `api_misuse` | API の誤使用 | 「非同期関数を await せずに呼び出した」 |
| `environment_issue` | 環境/設定の問題 | 「システム依存関係が不足している」 |

予防ルールは `CLAUDE.md` の `## Bug Prevention Rules` セクションに書き込まれます。次回セッションでは CLAUDE.md が system prompt として自動ロードされ、Agent は **同じミスを二度と繰り返しません**。

---

## データモデル

```python
class BugRecord(BaseModel):
    # ── 必須フィールド ──
    bug_title: str              # 短い説明
    error_log_snippet: str      # エラーメッセージ / スタックトレース
    tried_methods: str          # 試行した方法（失敗も含む）
    final_solution: str         # 最終的な修正方法

    # ── オプションフィールド ──
    project_name: str | None
    tech_stack: str | None
    root_cause: str | None

    # ── システム管理 ──
    record_id: str | None       # MD5(bug_title + error_log_snippet) — 自動計算
    create_time: str            # ISO-8601 UTC タイムスタンプ（自動生成）
```

**record_id の自動計算**：
```python
@model_validator(mode="after")
def _compute_record_id(self) -> "BugRecord":
    import hashlib
    raw = (self.bug_title + self.error_log_snippet).encode("utf-8")
    self.record_id = hashlib.md5(raw).hexdigest()
    return self
```

---

## デプロイ

### MCP 設定

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory", "/絶対パス/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

> **設定場所：** Claude Code: `~/.claude/settings.json` | Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

### 環境変数

| 変数 | デフォルト値 | 説明 |
|------|------------|------|
| `BUGVAULT_EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding モデル（日中英対応） |
| `BUGVAULT_TOP_K` | `5` | 最大検索結果数 |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | LLM 判定評価を有効化 |
| `BUGVAULT_EVAL_LLM_API_KEY` | `""` | 判定 LLM の API キー |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | 振り返りツールを有効化 |

---

## 開発

```bash
uv run pytest -v                                    # 全 43 テスト
uv run pytest tests/test_core.py -v                 # ユニットテスト
uv run pytest tests/test_v2_services.py -v          # 振り返り + RAG 評価
uv run pytest tests/test_integration.py -v          # 統合テスト（~15s）
```

---

## 技術スタック選定理由

| 判断 | 理由 | 参考 |
|------|------|------|
| **なぜ MCP なのか？** | "Write once, run everywhere" — あらゆる MCP クライアントで動作。ローカル stdio 通信、ポート不要、ネットワーク不要。 | [why-not-skill.md](docs/refer/分析/02.なぜskillではないのか.md) |
| **なぜ LanceDB なのか？** | ゼロ運用の組込データベース（ベクトル版 SQLite）。MVCC でロックフリー同時実行。ネイティブ FTS + メタデータフィルタリング。 | [why-lancedb.md](docs/refer/分析/03.なぜLanceDBなのか.md) |
| **なぜ LangChain を使わないのか？** | 線形 CRUD + ベクトル検索 — フレームワークは抽象化のコストだけを増やす。BugVault は推論エンジンではなくツールエンドポイント。 | [why-sdk.md](docs/refer/分析/04.なぜSDKなのか.md) |
| **なぜ Cross-Encoder で ColBERT ではないのか？** | ColBERT は独立した PyTorch インデックス(~1.5GB)が必要。20 件の再ランクには Cross-Encoder ONNX(80MB) の方が高精度で依存も少ない。 | [ADR](docs/refer/02設計/adr-cross-encoder-vs-colbert.md) |
| **なぜ二重フォールバックが必要か？** | 小規模 LLM は複雑な CoT プロンプトで JSON フォーマットに失敗しやすい。クォータ＋例外の二重保護で評価リンクの異常が検索に影響しない。 | [v1.1 アーキテクチャ](docs/refer/02設計/04.v1.1-architecture.md) |
|------|------|
| **なぜ `threading.Lock` が必要？** | LanceDB の `_table` は並行アクセス時に最新バージョンを保証しない |
| **なぜ `mode='overwrite'`？** | `drop_table + create_table` が古いバージョン参照を残し "file not found" の原因に |
| **なぜ `response_format=json_object`？** | 強制しないと LLM が JSON を fence で囲み解析エラーに |
| **なぜ 0.55 の意味閾値？** | ANN 距離 ~0.90 に相当、経験的に閾値以下は完全に無関係 |
| **なぜ 3 軸 RAGAS？** | 単一スコアは「検索不良」と「幻覚」を混同。3 軸で区別 |

---

## トラブルシューティング

| 問題 | 解決策 |
|------|--------|
| Embedding モデルがプロキシで失敗 | `unset all_proxy ALL_PROXY`；`~/.cache/fastembed/` にキャッシュ |
| Claude Code にツールが表示されない | 絶対パス設定を確認；`uv run python -m bugvault.main` の動作確認 |
| LanceDB の "file not found" | `rm -rf ~/.bugvault/lancedb` して再起動（v3 で `overwrite` 修正済み） |

---

## ライセンス

MIT

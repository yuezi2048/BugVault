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

### v1.1.1 新機能 — 親子チャンク検索

- **🧩 チャンク単位のベクトルインデックス** — 各バグ記録が 1 つの長いベクトルではなく **2 つの短いベクトル** を生成：
  `error_log` チャンク（正確なエラーマッチング）+ `semantic` チャンク（タイトル + 試行方法 + 解決策）、独立した `bugvault_chunks` テーブルに保存
- **🎯 精度の高い検索** — 特定のスタックトレースを検索すると `error_log` チャンクに直接ヒットし、長い `final_solution` で希釈されない
- **🔄 親ドキュメントマッピング** — チャンクレベル RRF 融合 → `parent_id` で重複排除 → `fetch_records_by_ids()` で完全なドキュメントを取得 → Cross-Encoder 再ランク
- **📦 デュアルテーブルアーキテクチャ** — `bug_records`（親メタデータ + FTS）+ `bugvault_chunks`（子ベクトル + フィルタ用の `tech_stack`/`project_name` 冗長カラム）
- **🏗️ `rebuild_index.py`** — 1 ソースレコードにつき 1 親レコード + 2 チャンクを生成
- **🔤 スマート技術スタックフィルター** — `target_tech_stack="Java"` が `"JavaScript"` に誤ヒットしません。
  除外辞書により `LIKE` のバージョンサフィックス柔軟性（例：`"Python"` → `"Python 3.13"`）を
  維持しつつ、クロス技術の誤検出を防止します。詳細は [P1 クローズ証明](docs/tests/v1.1.1-test-report.md#8-v111-p1-問題闭环証明) を参照。

### 3 つのツール

BugVault はバグ修正ライフサイクル全体をカバーする 3 つの MCP ツールを公開し、**各ツールは単一責任** を持ちます：

| ツール | 責任 | オプション |
|--------|------|-----------|
| `retrieve_bug_experience` | 🛠️ トラブル中 — 意味検索 + 精密再ランク + RAG 品質評価 | 評価はオプション |
| `save_bug_experience` | 💾 解決後 — Markdown 即時保存 + バックグラウンド非同期ベクトル登録 | 非同期はオプション |
| `reflect_and_prevent_error` | 🧠 振り返り — 根本原因の分類 + CLAUDE.md への予防ルール書き込み | ✅ オプション |

### 主な機能

### v1.1 新機能

- **🎯 ハイブリッド検索** — ベクトル + FTS 全文検索の二系統を RRF(k=60) で融合、詳細は [v1.1 アーキテクチャ](docs/refer/设计/04.v1.1-architecture.md) 参照
- **⚡ Cross-Encoder 再ランク** — 軽量 ONNX モデルで 2 次スコアリング、[ADR 選定記錄](docs/refer/设计/adr-cross-encoder-vs-colbert.md) 参照
- **🧪 Claim-Level 評価** — CoT 思考連鎖で声明抽出 → 逐一検証 → `claims_analysis[]` 出力、[評価戦略](docs/refer/设计/evaluation-strategy.md) および [v1.1 アーキテクチャ](docs/refer/设计/04.v1.1-architecture.md#二評価リンク戦略パターン--二重フォールバック) 参照
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

# 検証（137+ テスト）
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

### 🐞 `BugRecord` — 保存/検索されたバグ記録

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `bug_title` | `str` (1-256) | ✅ | 短いタイトル |
| `error_log_snippet` | `str` (1-32768) | ✅ | エラーメッセージまたはスタックトレース |
| `tried_methods` | `str` (1-8192) | ✅ | 試行済みの方法 |
| `final_solution` | `str` (1-16384) | ✅ | 最終的な修正 |
| `project_name` | `str \| None` | ❌ | プロジェクト名 |
| `tech_stack` | `str \| None` | ❌ | 技術スタックタグ（例："Python 3.13, Django"） |
| `root_cause` | `str \| None` | ❌ | 根本原因分析（≤4096 文字） |
| `record_id` | `str \| None` | 🛠️ 自動 | MD5(`bug_title` + `error_log_snippet`) — 重複排除キー |
| `create_time` | `str` | 🛠️ 自動 | ISO-8601 UTC タイムスタンプ |

### 📊 `RAGEvalResult` — 評価出力（全フィールド任意）

| フィールド | 型 | 範囲 | 説明 |
|-----------|-----|------|------|
| `strategy_used` | `str` | `simple` / `claim_level` / `simple (fallback_from_error)` | 実際に実行された戦略 |
| `rag_confidence_score` | `float \| None` | 0-10 | 合成スコア：`faithfulness×5 + context_relevance` |
| `context_relevance` | `float \| None` | 0.0-5.0 | 検索文書のクエリ関連性 |
| `faithfulness` | `float \| None` | 0.0-5.0 (simple) / 0.0-1.0 (claim_level) | ソース文書に裏付けられた主張の割合 |
| `evaluation` | `str \| None` | — | `justification` の別名 |
| `justification` | `str \| None` | — | 減点理由の厳しい説明 |
| `claims_analysis` | `list[dict] \| None` | — | 主張レベル：`[{claim, supported, reason}]` |
| `suggested_action` | `str \| None` | `CONFIDENT` / `PARTIAL` / `CAUTION` / `INSUFFICIENT` | Agent への構造化提案 |
| `prompt_tokens` | `int \| None` | — | 判定 LLM に送信された prompt token 数 |
| `completion_tokens` | `int \| None` | — | 判定 LLM からの completion token 数 |
| `total_tokens` | `int \| None` | — | 評価で消費された総 token 数 |

### 🛠️ ツール：`retrieve_bug_experience` — リクエストパラメータ

| パラメータ | 型 | 必須 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| `query` | `string` | ✅ | — | エラーメッセージ、スタックトレース、バグの説明 |
| `eval_depth` | `enum` | ❌ | `"simple"` | `"none"` / `"simple"` / `"claim_level"` |
| `target_tech_stack` | `string` | ❌ | — | 技術スタックフィルター（例：`"Python"`）、大文字小文字を区別しない |
| `target_project_name` | `string` | ❌ | — | プロジェクト名フィルター（例：`"order-svc"`）、大文字小文字を区別しない |

**戻り値：** フォーマットされたテキストブロック：
1. `--- Retrieval Info ---` — 使用戦略（hybrid / vector-only）+ ソース数
2. `--- Result N ---` — 取得された各バグ記録（タイトル、プロジェクト、エラー、試行、解決策、根本原因）
3. `--- RAG Evaluation ---` — 信頼度スコア、トークン使用量、主張分析（`eval_depth != "none"` の場合）

### 💾 ツール：`save_bug_experience` — リクエストパラメータ

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `bug_title` | `string` | ✅ | 短いタイトル |
| `error_log_snippet` | `string` | ✅ | エラーメッセージまたはスタックトレース |
| `tried_methods` | `string` | ✅ | 試行済みの方法 |
| `final_solution` | `string` | ✅ | 最終的な修正 |
| `project_name` | `string` | ❌ | プロジェクト名（任意） |
| `tech_stack` | `string` | ❌ | 技術スタックタグ（任意） |
| `root_cause` | `string` | ❌ | 根本原因分析（任意） |

### 📝 ツール：`reflect_and_prevent_error` — リクエストパラメータ

| パラメータ | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `reflection_text` | `string` | ✅ | バグ原因の詳細分析 |
| `error_category` | `enum` | ✅ | `understanding_bias` / `code_logic_error` / `api_misuse` / `environment_issue` / `other` |
| `preventive_rule` | `string` | ✅ | 再発防止のための実行可能なルール |

---

### キー設定

| 変数 | デフォルト値 | 説明 |
|------|------------|------|
| `BUGVAULT_DATA_ROOT` | `~/.bugvault` | LanceDB + アーカイブのルート |
| `BUGVAULT_ENABLE_RAG_EVAL` | `false` | LLM 判定評価を有効化 |
| `BUGVAULT_EVAL_LLM_API_KEY` | `""` | 判定 LLM の API キー |
| `BUGVAULT_EVAL_LLM_MODEL` | `gpt-4o-mini` | 判定モデル名 |
| `BUGVAULT_EVAL_LLM_BASE_URL` | `https://api.openai.com/v1` | カスタム API エンドポイント |
| `BUGVAULT_TOP_K` | `5` | 最大検索結果数 |
| `BUGVAULT_ENABLE_FTS` | `true` | 全文検索の二系統検索を有効化 |
| `BUGVAULT_ENABLE_RERANKER` | `true` | Cross-Encoder 再ランクを有効化 |
| `BUGVAULT_RERANKER_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | Cross-Encoder モデル名 |
| `BUGVAULT_ENABLE_RECENCY_DECAY` | `false` | 時間減衰（デフォルト無効、古いバグも同等に評価） |
| `BUGVAULT_MAX_CLAIM_EVALS_PER_SESSION` | `10` | Claim-level サーキットブレーカー上限 |
| `BUGVAULT_ENABLE_REFLECTION_TOOL` | `true` | 振り返りツールを有効化 |
| `BUGVAULT_THREAD_POOL_WORKERS` | `2` | 非同期 I/O スレッド数 |

完全なリストは [.env.example](.env.example)（20+ 項目）を参照。

---

## 開発

```bash
uv run pytest -v                                    # 全 137 テスト
uv run pytest tests/test_core.py -v                 # ユニットテスト
uv run pytest tests/test_v2_services.py -v          # 振り返り + RAG 評価
uv run pytest tests/test_integration.py -v          # 統合テスト（~15s）
```

---

## 技術スタック選定理由

| 判断 | 理由 | 参考 |
|------|------|------|
| **なぜ MCP なのか？** | "Write once, run everywhere" — あらゆる MCP クライアントで動作。ローカル stdio 通信、ポート不要、ネットワーク不要。 | [why-not-skill.md](docs/refer/分析/02.为什么不做成skill.md) |
| **なぜ LanceDB なのか？** | ゼロ運用の組込データベース（ベクトル版 SQLite）。MVCC でロックフリー同時実行。ネイティブ FTS + メタデータフィルタリング。 | [why-lancedb.md](docs/refer/分析/03.为什么选择LanceDB.md) |
| **なぜ LangChain を使わないのか？** | 線形 CRUD + ベクトル検索 — フレームワークは抽象化のコストだけを増やす。BugVault は推論エンジンではなくツールエンドポイント。 | [why-sdk.md](docs/refer/分析/04.为什么选择SDK.md) |
| **なぜ Cross-Encoder で ColBERT ではないのか？** | ColBERT は独立した PyTorch インデックス(~1.5GB)が必要。20 件の再ランクには Cross-Encoder ONNX(80MB) の方が高精度で依存も少ない。 | [ADR](docs/refer/设计/adr-cross-encoder-vs-colbert.md) |
| **なぜ二重フォールバックが必要か？** | 小規模 LLM は複雑な CoT プロンプトで JSON フォーマットに失敗しやすい。クォータ＋例外の二重保護で評価リンクの異常が検索に影響しない。 | [v1.1 アーキテクチャ](docs/refer/设计/04.v1.1-architecture.md) |
| **なぜ親子チャンク分割（v1.1.1）？** | 1 レコード 1 ベクトルでは `final_solution` が長いと `error_log_snippet` の特徴が希釈される。`error_log` チャンクと `semantic` チャンクの 2 つに分割し、チャンクレベル RRF + `parent_id` で統合することで精度が向上する。 | [v1.1.1 設計](docs/refer/设计/) |
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

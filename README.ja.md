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

BugVault は **ローカルファーストの MCP（Model Context Protocol）サーバー** であり、Claude をはじめとする MCP 対応 LLM クライアントに、セッションを超えた永続的なバグデバッグ記憶を提供します。

**課題：** LLM でバグを調査するたびに、毎回ゼロからのスタートになります。数日後に同じ問題が再発しても、LLM は以前の修正方法を覚えていません。あなたの貴重なデバッグ経験は無駄になってしまいます。

**BugVault の解決策：** LLM の専用「バグ脳」として機能し、`save_bug_experience` で解決済みのバグを自動保存し、`retrieve_bug_experience` で過去の解決策を検索します。すべてのデータは **100% ローカル** に保存 — クラウドなし、API 費用なし、データ漏洩なし。

### 主な機能

- **意味検索** — キーワードではなく自然言語で過去のバグを検索
- **自動保存** — 4 つの必須フィールドのみで、手間ゼロでデバッグ記録を保存
- **スマートトランケーション** — スタックトレースを自動でトリミング、トークンを節約しつつ重要な情報を保持
- **時間減衰再ランキング** — 最近の解決策を優先、古いものは自動的に重み減少
- **純粋ローカル** — データは `~/.bugvault/` に保存。ネットワーク不要
- **MCP ネイティブ** — Claude Desktop、Claude Code、Cursor、Cline、Windsurf など対応

---

## クイックスタート

### 前提条件

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（パッケージマネージャー）

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/yourusername/bugvault.git
cd bugvault

# 依存関係をインストール（GPU 不要）
uv sync

# ユニットテストを実行
uv run pytest tests/test_core.py -v
```

### 公開 MCP ツール

設定後、Claude は 2 つの追加ツールを使用できます：

| ツール | 説明 | 必須フィールド |
|--------|------|----------------|
| `retrieve_bug_experience` | エラー内容で過去の解決策を検索 | `query` |
| `save_bug_experience` | 解決済みバグを知識ベースに保存 | `bug_title`, `error_log_snippet`, `tried_methods`, `final_solution` |

---

## アーキテクチャ

```
┌──────────────────────────────────────────────────────┐
│          MCP クライアント (Claude Code / Desktop)      │
└───────────────────────┬──────────────────────────────┘
                        │ JSON-RPC via stdio
┌───────────────────────▼──────────────────────────────┐
│                BugVault MCP サーバー                    │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │  mcp_tools/  (ファサード層)                      │  │
│  │  ┌───────────────────┐ ┌───────────────────┐   │  │
│  │  │  retrieve_bug_    │ │  save_bug_        │   │  │
│  │  │  experience       │ │  experience       │   │  │
│  │  └────────┬──────────┘ └────────┬──────────┘   │  │
│  └───────────┼──────────────────────┼──────────────┘  │
│              │                      │                 │
│  ┌───────────▼──────────────────────▼──────────────┐  │
│  │  services/  (ビジネスロジック層)                 │  │
│  │  ┌──────────────────────┐ ┌──────────────────┐  │  │
│  │  │  RetrievalService    │ │ IngestionService │  │  │
│  │  │  · ANN 検索          │ │ · バリデーション │  │  │
│  │  │  · 時間減衰再ランク  │ │ · 質問生成       │  │  │
│  │  │  · スタックトランケ  │ │ · MD アーカイブ  │  │  │
│  │  └──────────┬───────────┘ └────────┬─────────┘  │  │
│  └─────────────┼──────────────────────┼────────────┘  │
│                │                      │               │
│  ┌─────────────▼──────────────────────▼────────────┐  │
│  │  database/  (永続層)                             │  │
│  │  ┌──────────────────┐  ┌────────────────────┐   │  │
│  │  │ LanceDBClient    │  │ Markdown Archive   │   │  │
│  │  │ (ベクトル+メタ)   │  │ (可読バックアップ)  │   │  │
│  │  └──────────────────┘  └────────────────────┘   │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

### 技術スタック

| コンポーネント | 選択 | 理由 |
|--------------|------|------|
| **MCP トランスポート** | 公式 Python `mcp` SDK、`stdio` モード | HTTP 不要、ポート不要、純粋なサブプロセス |
| **ベクトル DB** | [LanceDB](https://lancedb.github.io/lancedb/) | ゼロ依存組み込み、MVCC、Arrow ネイティブ |
| **Embedding** | [fastembed](https://github.com/qdrant/fastembed) (`BAAI/bge-small-zh-v1.5`) | 軽量 ONNX Runtime、PyTorch/CUDA 不要 |
| **バリデーション** | Pydantic v2 | コンパイル時型安全性、高速バリデーター |
| **設定** | Pydantic Settings | `.env` / 環境変数による設定 |
| **実行環境** | Python 3.13+ | モダンな非同期処理、改善されたエラーメッセージ |

---

## 使い方

### MCP サーバーとしてデプロイ

BugVault は MCP の **stdio トランスポート** で通信します — MCP クライアントの子プロセスとして動作します。HTTP サーバーの起動もポートの設定も不要です。

#### Claude Code CLI の設定

Claude Code は `~/.claude/settings.json` から MCP サーバー設定を読み込みます。`mcpServers` に BugVault を追加します：

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

> **重要：** `uv` のパスとプロジェクトディレクトリは **絶対パス** を使用してください。`~` や相対パスは使わないでください。

設定後、Claude Code を再起動します。サーバーは **遅延起動** します — ツール（`save_bug_experience` または `retrieve_bug_experience`）を初めて呼び出したときに起動します。初回コールドスタートは約 3〜5 秒かかります（Embedding モデルのダウンロード/ロードと LanceDB 接続）。

サーバーの状態確認：

```
/mcp
```

#### Claude Desktop の設定

`claude_desktop_config.json` に以下を追加：

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

`claude_desktop_config.json` の場所：
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

### デプロイの確認

1. Claude Code または Claude Desktop で会話を開始
2. Claude にテストレコードを保存させる
3. Claude にそのレコードを検索させる

デプロイが成功していれば、Claude が MCP ツールを呼び出して結果を返します。

### 手動テスト

```bash
# サーバーを直接起動（デバッグ時は stdout/stderr を結合）
uv run python -m bugvault.main 2>&1

# ユニットテストを実行
uv run pytest tests/test_core.py -v

# 統合テストを実行（サブプロセス自動起動）
uv run pytest tests/test_integration.py -v -m e2e
```

---

## デプロイトラブルシューティング

### よくあるエラーと解決策

#### 1. 接続切断/プロセスクラッシュ

```
[MCP エラー] CONNECTION_CLOSED または Connection closed
```

**原因：** サーバープロセスが起動時にクラッシュ — 特に Embedding モデル読み込みや LanceDB 初期化中。

**診断：**
```bash
# 手動でサーバーを起動しエラーを確認
uv run python -m bugvault.main 2>&1
```

**解決策：**
- `uv sync` が正常に完了していることを確認
- Python バージョンを確認：`python --version`（3.13+ が必要）
- 初回実行時はモデルダウンロードのためネットワーク接続が必要
- プロキシ環境の場合：`unset all_proxy ALL_PROXY`

#### 2. テーブル/DB が既に存在するエラー

```
ValueError: Table 'bug_records' already exists
```

**原因：** 以前のセッションで作成された LanceDB テーブルが残っている。

**解決策：** 最新コードでは既存テーブルを自動的に開くように修正済み。リセットする場合：
```bash
rm -rf ~/.bugvault/lancedb/bug_records*
```

#### 3. サーバーは起動するが Claude Code にツールが表示されない

**原因：** Claude Code はサーバーが `initialize` ハンドシェイクに正常応答した後にツールを認識します。ハンドシェイク前にクラッシュするとツールは登録されません。

**診断：**
- `/mcp` を実行して登録済み MCP サーバーを確認
- BugVault が "error" または "not running" と表示される場合：`cat ~/.claude/logs/*.log`
- 手動でサーバーが正常起動するか確認：`uv run python -m bugvault.main 2>&1 | head -20`

**よくある原因：**
- **`uv` のパスが間違っている：** `which uv` で絶対パスを確認
- **プロジェクトパスが相対パス：** `--directory` は絶対パスで指定
- **作業ディレクトリが間違っている：** BugVault プロジェクトルートで実行

#### 4. Embedding モデルのダウンロード失敗

```
ConnectionError: HTTPSConnectionPool ... Name or service not known
```

**解決策：**
- 初回ダウンロードはネットワーク接続が必要（約 90 MB）
- `BUGVAULT_EMBEDDING_MODEL` で別のモデルを指定可能
- キャッシュ場所：`~/.cache/fastembed/` — 一度ダウンロードすればオフラインでも使用可能
- プロキシ環境：ダウンロード時はプロキシ設定を解除

#### 5. インポートエラー

```
ImportError: cannot import name '...' from 'bugvault...'
```

**解決策：** Python パスが正しく設定されているか確認：
```bash
cd /絶対パス/bugvault
PYTHONPATH=src uv run python -m bugvault.main
```

#### 6. LanceDB / PyArrow バージョン不一致

```
ValueError: The LanceDB table has not been created with the same schema
```

**解決策：** 開発中にスキーマが変更された場合は古いデータを削除：
```bash
rm -rf ~/.bugvault/lancedb
uv run pytest tests/test_integration.py -v -m e2e
```

### チェックリスト

```
□ uv sync がエラーなく完了
□ Python 3.13+ がアクティブ (python --version)
□ uv パスが絶対パス (which uv)
───
□ ~/.claude/settings.json が絶対パスを使用
□ --directory が pyproject.toml のあるプロジェクトルートを指している
───
□ 初回モデルダウンロード時にインターネットアクセス可能
□ ~/.bugvault/lancedb が書き込み可能
───
□ uv run python -m bugvault.main  がエラーなく起動
□ uv run pytest tests/ -v         全テストがパス
```

---

## プロジェクト構成

```
bugvault/
├── pyproject.toml               # プロジェクト設定と依存関係
├── .env.example                 # 環境変数テンプレート
├── README.md
├── src/
│   └── bugvault/
│       ├── main.py              # MCP サーバーエントリーポイント（約 70 行）
│       ├── config.py            # Pydantic 設定（環境変数ベース）
│       ├── models/
│       │   └── bug_record.py    # BugRecord データモデル
│       ├── services/
│       │   ├── retrieval_svc.py # ANN 検索 + 再ランク + トランケーション
│       │   └── ingestion_svc.py # バリデーション + 質問生成 + MD アーカイブ
│       ├── database/
│       │   └── lancedb_client.py# LanceDBClient OOP データアクセス層
│       ├── mcp_tools/
│       │   └── tools.py         # MCP ツール登録 + ハンドラー
│       └── utils/
│           ├── stdout_guard.py  # MCP stdout 保護
│           ├── logger.py        # stderr 専用ロギング
│           └── text_utils.py    # スタックトレーストランケーション
└── tests/
    ├── test_core.py             # 15 ユニットテスト
    ├── test_mcp_protocol.py     # E2E プロトコルテスト
    └── test_integration.py      # 保存→取得統合テスト
```

---

## データモデル

```python
class BugRecord(BaseModel):
    # ── 必須フィールド ──
    bug_title: str              # 短い説明
    error_log_snippet: str      # エラーメッセージ / スタックトレース
    tried_methods: str          # 試行した方法（失敗も含む）
    final_solution: str         # 最終的な修正方法

    # ── オプションフィールド（非同期補完対応）──
    project_name: str | None
    tech_stack: str | None
    root_cause: str | None

    # ── システム管理 ──
    create_time: str            # ISO-8601 タイムスタンプ（自動生成）
```

---

## 開発ガイド

### テストの実行

```bash
# ユニットテスト（高速、外部依存なし）
uv run pytest tests/test_core.py -v

# E2E 統合テスト（実際のサブプロセス起動）
uv run pytest tests/test_integration.py -v -m e2e

# 全テスト
uv run pytest tests/ -v
```

### 設定オプション

環境変数（接頭辞 `BUGVAULT_`）または `.env` ファイルで設定：

```bash
BUGVAULT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
BUGVAULT_TOP_K=5
BUGVAULT_RECENCY_WEIGHT=0.3
BUGVAULT_RECENCY_HALF_LIFE_DAYS=90
BUGVAULT_THREAD_POOL_WORKERS=2
```

全オプションは [.env.example](.env.example) を参照。

---

## MCP Stdio トランスポートの仕組み

BugVault は **stdio トランスポート** — 最もシンプルな MCP 通信モードを使用します：

```
┌─────────────────────┐          JSON-RPC 2.0          ┌─────────────────────┐
│   MCP クライアント   │  ──────────────────────────►   │   BugVault サーバー │
│  (Claude Code /     │  stdin（サーバーに書き込み）    │  (uv run python     │
│   Claude Desktop)   │  ◄──────────────────────────   │   -m bugvault.main) │
│                     │  stdout（サーバーから読み取り）  │                     │
└─────────────────────┘                                └─────────────────────┘
                                                              │ stderr（ログ）
                                                              ▼
                                                        端末 / ログファイル
```

重要なポイント：
- MCP クライアントは `uv run python -m bugvault.main` で BugVault を**子プロセスとして起動**
- クライアントはサーバーの **stdin** に JSON-RPC リクエストを書き込む
- サーバーは **stdout**（クライアントが読み取り）に JSON-RPC レスポンスを書き込む
- **stderr はログ出力用** — 端末には表示されるが MCP プロトコルでは無視される
- `_MCPStdoutProxy` ガードにより、誤った `print()` 呼び出しがプロトコルストリームを汚染するのを防止

`uv run python -m bugvault.main 2>&1` でログ出力のみ表示され JSON-RPC トラフィックが表示されないのはこのためです — JSON は stdout に送られますが、クライアントが stdin にリクエストを書き込んでいないと意味をなしません。

---

## 設計判断

- **なぜ LangChain を使わないのか？** BugVault のロジックは線形 CRUD + ベクトル検索です。フレームワークは不必要な抽象化をもたらすだけです。ネイティブ MCP SDK はスタックを浅く保ち、デバッグを容易にします。
- **なぜ FastAPI を使わないのか？** MCP の `stdio` モードは HTTP ではなく stdin/stdout で通信します。FastAPI は SSE（HTTP）トランスポートでのみ意味があり、ポート管理と依存関係の負荷が増えます。
- **なぜ sentence-transformers ではなく fastembed なのか？** `pip install sentence-transformers` は CPU オンリーのマシンでも PyTorch + NVIDIA CUDA ライブラリ（約 2.5 GB）をダウンロードします。fastembed は純粋な ONNX Runtime（約 30 MB）のみを使用します — GPU 不要。
- **なぜ Content-Length フレーミングではないのか？** MCP Python SDK の `stdio_server()` は、仕様に記載されている Content-Length フレーミングではなく、改行区切り JSON（1 行に 1 つの JSON オブジェクト）を使用します。

---

## トラブルシューティング

| 問題 | 解決策 |
|------|--------|
| Embedding モデルのダウンロードがプロキシで失敗 | `unset all_proxy ALL_PROXY`（fastembed は直接 HTTP を使用） |
| E2E テストがタイムアウト | 初回実行はモデルダウンロード（約 1 分）；以降は約 15 秒 |
| サーバー起動時に出力がない | ログは stderr に出力 — `uv run python -m bugvault.main 2>&1` を使用 |
| Claude Code にツールが表示されない | `~/.claude/settings.json` の絶対パス設定を確認 |
| "Connection closed" エラー | サーバー初期化中にクラッシュ — 手動 `2>&1` でトレースバック確認 |
| スキーマ更新後の LanceDB エラー | `rm -rf ~/.bugvault/lancedb` して再起動 |

---

## ロードマップ

- **v1.0（MVP）** — コア MCP サーバー + save/retrieve + LanceDB + embedding
- **v1.1** — 時間減衰再ランキング、フィールド別質問生成、.md 一括インポート
- **v1.2** — 知識グラフ可視化、VSCode/Cursor 拡張

---

## ライセンス

MIT
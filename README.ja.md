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
│  │  │ LanceDB          │  │ Markdown Archive   │   │  │
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

### Claude Desktop の設定

`claude_desktop_config.json` に以下を追加：

```json
{
  "mcpServers": {
    "bugvault": {
      "command": "/path/to/uv",
      "args": [
        "run",
        "--directory", "/path/to/bugvault",
        "python", "-m", "bugvault.main"
      ]
    }
  }
}
```

### 手動テスト

```bash
# サーバーを直接起動
uv run python -m bugvault.main

# E2E プロトコルテストを実行（サブプロセスを自動起動）
uv run python tests/test_mcp_protocol.py
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
│       ├── main.py              # MCP サーバーエントリーポイント
│       ├── config.py            # Pydantic 設定（環境変数ベース）
│       ├── models/
│       │   └── bug_record.py    # BugRecord データモデル
│       ├── services/
│       │   ├── retrieval_svc.py # ANN 検索 + 再ランク + トランケーション
│       │   └── ingestion_svc.py # バリデーション + 質問生成 + MD アーカイブ
│       ├── database/            # LanceDB クライアント
│       ├── mcp_tools/           # ツール定義（ファサード層）
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

# E2E プロトコルテスト（実際のサブプロセス起動、約 15 秒）
uv run python tests/test_mcp_protocol.py

# 統合テスト（保存→取得のラウンドトリップ）
uv run pytest tests/test_integration.py -v -s

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

---

## ロードマップ

- **v1.0（MVP）** — コア MCP サーバー + save/retrieve + LanceDB + embedding
- **v1.1** — 時間減衰再ランキング、フィールド別質問生成、.md 一括インポート
- **v1.2** — 知識グラフ可視化、VSCode/Cursor 拡張

---

## ライセンス

MIT

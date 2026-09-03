# 扫描件 PDF 表格提取工具

从扫描版 PDF（图纸/工程表格）中识别表格，写入 SQLite，便于后续搜索。

## 功能

- 扫描件：线条检测 + RapidOCR（ONNXRuntime）中文识别
- 自动跳过无表格图纸页
- 表名 / 内容入库，支持界面搜索与 FTS
- 图形界面 + 命令行

## 本机开发安装

```bash
pip install -r requirements.txt
python main.py
```

## 给客户交付（推荐绿色免安装包）

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_green.ps1
```

产物：`release\PdfTableExtractor_green.zip`（通常约 100MB 量级）

客户：解压 → 双击 `run.bat`  
**无需安装 Python、无需联网、不挑本机 Python 版本。**

### 备选：客户已有匹配版本的 Python

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\build_offline_python.ps1
```

产物：`release\PdfTableExtractor_python_offline.zip`  
客户：`install.bat` → `run.bat`（Python 主次版本需一致）。

## 命令行示例

```bash
python main.py --cli --pdf "S4-7 涵洞.pdf" --db "S4-7_tables.db" --page-from 4 --page-to 5
```

## 说明

- 含表页 OCR 通常秒级到几十秒（比旧版 Paddle 轻很多）
- 旧版 Paddle 大包（`PdfTableExtractor_内网离线版.zip`）可废弃

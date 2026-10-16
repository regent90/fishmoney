# 16688 貨源客戶端

只管貨源對接:簽章、詢價、下單、查單、投訴。不含網站、前端、收款。
只用 Python 標準庫(3.10+)。

## 設定

密鑰不要寫進程式或貼進聊天。app_id 和 secret 在 16688 後台「開放平台」。

最簡單:把 `.env.example` 複製成 `.env`(同一個資料夾),自己填入兩個值。`.env` 已被 `.gitignore` 排除。環境變數優先於 `.env`。

或用環境變數:

```powershell
$env:SIXTEEN688_APP_ID = ""
$env:SIXTEEN688_SECRET = ""
```

## 指令

唯讀,不花錢:

```bash
python cli.py list --keywords gemini        # 已代理到你帳號的貨源
python cli.py detail SG20001                # 商品詳情
python cli.py quote SG20001 -n 1            # 單價、手續費、庫存、錢包餘額是否足夠
python cli.py query T2603161200001          # 查採購單(預設不印卡密)
python cli.py dry-run openApi/purchase/quotePrice goods_no=SG20001 quantity=1   # 只印簽好的請求,不送出(路徑不要加開頭斜線,避免 Git Bash 把它轉成 Windows 路徑)
```

會扣運營錢包:

```bash
python cli.py buy SG20001 -n 1 --max-total 6.0 --yes
```

`buy` 的保護:沒有 `--yes` 拒絕;先詢價,超過 `--max-total`、庫存不足、餘額不足都不會下單;下單後寫入 `ledger.jsonl`(只記單號與金額,不記卡密);未發貨會輪詢 `purchase/query`,因為 API 沒有回調。

## 測試

```bash
python -m unittest -v
```

離線測試,不連網。簽章演算法是照官方文件實作,**還沒有和真伺服器對過**。第一次用真憑證請先跑 `quote`(唯讀),回 `code=1` 就代表簽章正確。

## 已知限制

- 文件寫 `quotePrice` 「僅已代理貨源商品」,`goods/list` 也只列已代理的貨源。所以貨源廣場的商品(商品編號長得像 `G53296780`)很可能要先在後台申請成為該貨源商的代理,才能用 API 詢價下單。這點我沒有驗證,第一次請先用 `quote` 試一個商品編號,看回傳的錯誤訊息。
- 浮點數簽章:整數值的浮點(10.0)轉成 "10",與 PHP 一致;帶小數的值依 Python 的 `str()`,若伺服器簽章不符請回報,可能要調整。
- 還沒做:`order/list`、`order/info`、商品與卡密管理端點(那些是賣方管理自己店的,不是進貨)。

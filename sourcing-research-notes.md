# 貨源研究進度筆記(2026-10-16)

## 已完成(公開資料)

### 獨角數卡 Dujiao-Next
- 「站點對接」只在 **Dujiao 站與 Dujiao 站之間**運作(下游拉上游商品、庫存,非同步下單、回調交付)。文件沒說支援非 Dujiao 的上游,所以**不能直接接 16688 貨源**,需自寫對接層。
- 上游 API(Base `/api/v1/upstream`):`/ping`、`/categories`、`/products`、`/products/:id`、`/orders`(錢包扣款)、`/orders/:id`、`/orders/:id/cancel`、回調 `/callback`。
- 簽章:HMAC-SHA256,標頭 `Dujiao-Next-Api-Key` / `-Timestamp` / `-Signature`,時間誤差上限 60 秒。API Key 需管理員核准。
- 庫存沒有獨立端點,看商品 SKU 的 `stock_status` / `stock_quantity`。
- 已對接商品不能手動或本地自動發貨,全靠上游回調;上游拒絕取消時,本地訂單無法退款。
- 支付渠道共 10 種:易支付(Epay)、PayPal、Stripe、支付寶、微信、TokenPay、BEpusdt、epusdt、OKPay、DujiaoPay。**沒有綠界、藍新**,文件也沒寫如何新增自訂渠道。DujiaoPay 可用 USD / HKD / CNY 計價。
- 文件頁:`/api/integration-guide`、`/api/integration-open-api`、`/payment/guide`、`/api/frontend-api`、`/community/projects`(尚未讀,可能有社區外掛)。

### Jio × Google AI Pro(供貨穩定性參考)
- Google 官方部落格確認有此合作。早期限 18–25 歲,後續報導稱擴大到 Unlimited 5G 用戶(未經一手來源證實)。
- 福利持續條件:維持 Unlimited 5G 方案(每月 349 盧比起)。**找不到官方條款原文**,撤銷規則未知。
- 官方領取方式是 MyJio App「Claim Now」並綁定自己的 Google 帳號,沒有公開的可轉讓啟動網址。這代表你買到的一次性網址很可能是從門號端批量取得的,**來源可查性低**。

## 被擋住(需要你操作)
- **16688 後台**:內建瀏覽器是獨立環境,沒有你的登入狀態,目前停在登入頁。公開網頁搜尋找不到 16688 的 API、費率、鯨商城 PRO 資料。
- **鏈動小鋪**:有阿里雲 WAF 驗證,依規定不繞過。

## 下一步
1. 你在內建瀏覽器登入 16688(郵箱或微信掃碼),我再讀貨源廣場、API、費率、規則。
2. 鏈動小鋪若要看,由你手動通過驗證。
3. 讀 Dujiao `/community/projects`,找綠界/藍新外掛。
4. 產出評分表與小量測試計畫。

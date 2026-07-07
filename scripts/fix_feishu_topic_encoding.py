from __future__ import annotations

import json
import os
from typing import Any

import httpx


BASE = "https://open.feishu.cn"
APP_TOKEN = "RqcTbRx11aX4Yvsj5ITcSEGtnAe"
TABLE_ID = "tblRmJfu5dpBGPpt"


def u(value: str) -> str:
    return value.encode("latin1").decode("unicode_escape")


TOPICS: list[dict[str, Any]] = [
    {"topic_id": "topic_026", "master_topic": u("\\u5b85\\u5efa\\u30b3\\u30fc\\u30c1\\u3067\\u72ec\\u5b66\\u5408\\u683c\\u3092\\u76ee\\u6307\\u3059\\u4f7f\\u3044\\u65b9"), "target_keyword": u("\\u5b85\\u5efa\\u30b3\\u30fc\\u30c1 \\u4f7f\\u3044\\u65b9"), "topic_cluster": "takken_exam_prep", "business_goal": "brand_awareness", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("\\u6539\\u7248\\u5f8c\\u306e\\u6838\\u5fc3\\u5165\\u53e3\\u30c6\\u30fc\\u30de\\u3002\\u5b85\\u5efa\\u30b3\\u30fc\\u30c1\\u306e\\u5b66\\u7fd2\\u30ed\\u30fc\\u30c9\\u30de\\u30c3\\u30d7\\u3001AI\\u554f\\u984c\\u6f14\\u7fd2\\u3001\\u5f31\\u70b9\\u5206\\u6790\\u3001\\u9032\\u6357\\u7ba1\\u7406\\u3092\\u7d39\\u4ecb\\u3059\\u308b\\u3002")},
    {"topic_id": "topic_027", "master_topic": u("\\u5b85\\u5efaAI\\u5b66\\u7fd2\\u30ed\\u30fc\\u30c9\\u30de\\u30c3\\u30d7\\u306e\\u4f5c\\u308a\\u65b9"), "target_keyword": u("\\u5b85\\u5efa AI \\u5b66\\u7fd2\\u30ed\\u30fc\\u30c9\\u30de\\u30c3\\u30d7"), "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("\\u6b8b\\u308a\\u65e5\\u6570\\u3001\\u5f31\\u70b9\\u79d1\\u76ee\\u3001\\u6bce\\u65e5\\u306e\\u5b66\\u7fd2\\u91cf\\u304b\\u3089\\u500b\\u5225\\u306e\\u5408\\u683c\\u8a08\\u753b\\u3092\\u4f5c\\u308b\\u30c6\\u30fc\\u30de\\u3002")},
    {"topic_id": "topic_028", "master_topic": u("\\u5b85\\u5efa\\u72ec\\u5b66\\u3067\\u632b\\u6298\\u3057\\u306a\\u3044\\u9031\\u9593\\u5b66\\u7fd2\\u8a08\\u753b"), "target_keyword": u("\\u5b85\\u5efa \\u72ec\\u5b66 \\u5b66\\u7fd2\\u8a08\\u753b"), "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "S", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": u("\\u72ec\\u5b66\\u53d7\\u9a13\\u8005\\u5411\\u3051\\u306b\\u3001\\u4e00\\u9031\\u9593\\u306e\\u5b66\\u7fd2\\u30ea\\u30ba\\u30e0\\u3068\\u5fa9\\u7fd2\\u65e5\\u3001\\u904e\\u53bb\\u554f\\u6f14\\u7fd2\\u3001\\u6a21\\u8a66\\u3092\\u6574\\u7406\\u3059\\u308b\\u3002")},
    {"topic_id": "topic_029", "master_topic": u("\\u5b85\\u5efa\\u521d\\u5fc3\\u8005\\u304c\\u6700\\u521d\\u306e7\\u65e5\\u9593\\u3067\\u3084\\u308b\\u3053\\u3068"), "target_keyword": u("\\u5b85\\u5efa \\u521d\\u5fc3\\u8005 \\u52c9\\u5f37\\u6cd5"), "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("\\u521d\\u5b66\\u8005\\u304c\\u5148\\u306b\\u5b66\\u3076\\u3079\\u304d\\u5168\\u4f53\\u50cf\\u3001\\u904e\\u53bb\\u554f\\u306e\\u4f7f\\u3044\\u65b9\\u3001\\u7fd2\\u6163\\u5316\\u306e\\u9032\\u3081\\u65b9\\u3092\\u6271\\u3046\\u3002")},
    {"topic_id": "topic_030", "master_topic": u("\\u5b85\\u5efa\\u306e\\u6a29\\u5229\\u95a2\\u4fc2\\u3092AI\\u3067\\u52b9\\u7387\\u3088\\u304f\\u899a\\u3048\\u308b\\u65b9\\u6cd5"), "target_keyword": u("\\u5b85\\u5efa \\u6a29\\u5229\\u95a2\\u4fc2 \\u899a\\u3048\\u65b9"), "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": u("\\u6c11\\u6cd5\\u30fb\\u6a29\\u5229\\u95a2\\u4fc2\\u306e\\u96e3\\u70b9\\u3092AI\\u89e3\\u8aac\\u3001\\u985e\\u984c\\u3001\\u9593\\u9055\\u3044\\u30ce\\u30fc\\u30c8\\u3067\\u7406\\u89e3\\u3059\\u308b\\u3002")},
    {"topic_id": "topic_031", "master_topic": u("\\u5b85\\u5efa\\u696d\\u6cd5\\u3092\\u5f97\\u70b9\\u6e90\\u306b\\u3059\\u308bAI\\u6f14\\u7fd2\\u6cd5"), "target_keyword": u("\\u5b85\\u5efa\\u696d\\u6cd5 \\u5f97\\u70b9\\u6e90"), "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("\\u5b85\\u5efa\\u696d\\u6cd5\\u306e\\u9ad8\\u914d\\u70b9\\u3092\\u6d3b\\u304b\\u3057\\u3001\\u77ed\\u5468\\u671f\\u306e\\u53cd\\u5fa9\\u6f14\\u7fd2\\u3068AI\\u89e3\\u8aac\\u3067\\u5b89\\u5b9a\\u3057\\u3066\\u5f97\\u70b9\\u3059\\u308b\\u3002")},
    {"topic_id": "topic_034", "master_topic": u("\\u5b85\\u5efa\\u904e\\u53bb\\u554f10\\u5e74\\u5206\\u306e\\u52b9\\u7387\\u7684\\u306a\\u56de\\u3057\\u65b9"), "target_keyword": u("\\u5b85\\u5efa \\u904e\\u53bb\\u554f 10\\u5e74\\u5206"), "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "S", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": u("\\u5e74\\u5ea6\\u5225\\u3001\\u79d1\\u76ee\\u5225\\u3001\\u8aa4\\u7b54\\u7387\\u9806\\u306e\\u904e\\u53bb\\u554f\\u6d3b\\u7528\\u6226\\u7565\\u3092\\u89e3\\u8aac\\u3059\\u308b\\u3002")},
    {"topic_id": "topic_035", "master_topic": u("\\u5b85\\u5efaAI\\u89e3\\u8aac\\u3067\\u9593\\u9055\\u3048\\u305f\\u554f\\u984c\\u3092\\u5fa9\\u7fd2\\u3059\\u308b\\u65b9\\u6cd5"), "target_keyword": u("\\u5b85\\u5efa AI \\u89e3\\u8aac \\u5fa9\\u7fd2"), "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("AI\\u89e3\\u8aac\\u3092\\u8aad\\u3080\\u3060\\u3051\\u3067\\u306a\\u304f\\u3001\\u8aa4\\u89e3\\u70b9\\u3092\\u7279\\u5b9a\\u3057\\u985e\\u984c\\u3067\\u5b9a\\u7740\\u3055\\u305b\\u308b\\u3002")},
    {"topic_id": "topic_037", "master_topic": u("\\u5b85\\u5efa\\u76f4\\u524d\\u671f30\\u65e5\\u306e\\u8ffd\\u3044\\u8fbc\\u307f\\u30b9\\u30b1\\u30b8\\u30e5\\u30fc\\u30eb"), "target_keyword": u("\\u5b85\\u5efa \\u76f4\\u524d\\u671f 30\\u65e5"), "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("\\u8a66\\u9a13\\u76f4\\u524d30\\u65e5\\u306e\\u5fa9\\u7fd2\\u3001\\u6a21\\u8a66\\u3001\\u6697\\u8a18\\u3001\\u5f31\\u70b9\\u88dc\\u5f37\\u3092\\u6574\\u7406\\u3059\\u308b\\u3002")},
    {"topic_id": "topic_040", "master_topic": u("\\u5b85\\u5efa\\u306e\\u5f31\\u70b9\\u5206\\u6790\\u3092AI\\u3067\\u81ea\\u52d5\\u5316\\u3059\\u308b\\u65b9\\u6cd5"), "target_keyword": u("\\u5b85\\u5efa \\u5f31\\u70b9\\u5206\\u6790 AI"), "topic_cluster": "takken_exam_prep", "business_goal": "technical_authority", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": u("\\u932f\\u984c\\u3001\\u79d1\\u76ee\\u3001\\u8ad6\\u70b9\\u3001\\u5b66\\u7fd2\\u6642\\u9593\\u304b\\u3089\\u5f31\\u70b9\\u3092\\u8a3a\\u65ad\\u3059\\u308b\\u3002")},
]


ADDITIONAL_TOPICS: list[dict[str, Any]] = [
    {"topic_id": "topic_041", "master_topic": "宅建の暗記カードをAIで作る方法", "target_keyword": "宅建 暗記カード AI", "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "一問一答、語呂合わせ、反復復習カードをAIで作り、スキマ時間の学習効率を上げる。"},
    {"topic_id": "topic_042", "master_topic": "宅建の語呂合わせ学習を効率化する方法", "target_keyword": "宅建 語呂合わせ 覚え方", "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "数字や頻出論点を覚えやすくする語呂合わせをAIで作る活用法。"},
    {"topic_id": "topic_043", "master_topic": "宅建アプリとAI学習サービスの違い", "target_keyword": "宅建 アプリ AI 学習", "topic_cluster": "takken_exam_prep", "business_goal": "brand_awareness", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "一般的な宅建アプリと宅建コーチ型AI学習の違いを比較し、使い分けを説明する。"},
    {"topic_id": "topic_044", "master_topic": "社会人が宅建に合格する朝夜学習ルーティン", "target_keyword": "社会人 宅建 勉強時間", "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "仕事前、通勤、夜学習を組み合わせた社会人向け宅建学習ルーティン。"},
    {"topic_id": "topic_047", "master_topic": "宅建5問免除とは何かをわかりやすく解説", "target_keyword": "宅建 5問免除", "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "5問免除の対象者、登録講習、メリット、注意点を初心者向けに整理する。"},
    {"topic_id": "topic_051", "master_topic": "不動産AIツールボックスの全体像と活用順序", "target_keyword": "不動産 AI ツールボックス", "topic_cluster": "real_estate_ai_tools", "business_goal": "brand_awareness", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "査定、集客、資金計算、契約支援、投資分析までTakkenAIの実務ツール群を整理する。"},
    {"topic_id": "topic_052", "master_topic": "不動産会社がAI導入で最初に自動化すべき業務", "target_keyword": "不動産会社 AI 導入", "topic_cluster": "real_estate_ai_tools", "business_goal": "technical_authority", "priority": "S", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "査定、チラシ、SNS投稿、顧客対応など、導入初期に効果が出やすい業務を解説する。"},
    {"topic_id": "topic_053", "master_topic": "不動産営業の追客をAIで効率化する方法", "target_keyword": "不動産 営業 追客 AI", "topic_cluster": "real_estate_ai_tools", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "顧客状態別の追客文、LINE、メール、電話前メモをAIで作る実務テーマ。"},
    {"topic_id": "topic_054", "master_topic": "不動産査定AIと人の査定を使い分ける方法", "target_keyword": "不動産 査定 AI", "topic_cluster": "area_research", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "AI査定の強みと限界を整理し、人の判断と組み合わせる実務的な使い方を説明する。"},
    {"topic_id": "topic_057", "master_topic": "不動産チラシの反応率を上げるAIコピー術", "target_keyword": "不動産 チラシ コピー", "topic_cluster": "property_marketing", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "物件チラシの見出し、キャッチコピー、写真説明、問い合わせ導線をAIで改善する。"},
    {"topic_id": "topic_059", "master_topic": "Instagram向け不動産投稿をAIで作る方法", "target_keyword": "不動産 Instagram 投稿 AI", "topic_cluster": "property_marketing", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "Instagram向けの物件投稿文、ハッシュタグ、画像説明、投稿構成をAIで作る。"},
    {"topic_id": "topic_060", "master_topic": "YouTubeショート向け物件動画台本の作り方", "target_keyword": "物件動画 台本 AI", "topic_cluster": "property_marketing", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "15秒、30秒、60秒の物件紹介動画台本をAIで設計する。"},
    {"topic_id": "topic_061", "master_topic": "LINEで使える不動産営業メッセージ例文", "target_keyword": "不動産 営業 LINE 例文", "topic_cluster": "property_marketing", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "来店前、内見後、価格相談、資料送付などLINE追客文例を整理する。"},
    {"topic_id": "topic_065", "master_topic": "賃貸初期費用をAIで説明資料にする方法", "target_keyword": "賃貸 初期費用 説明", "topic_cluster": "finance_calculation", "business_goal": "traffic_reach", "priority": "B", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "敷金、礼金、仲介手数料、保証料などを顧客向けにわかりやすく説明する。"},
    {"topic_id": "topic_068", "master_topic": "店舗物件の商圏分析をAIで効率化する方法", "target_keyword": "店舗物件 商圏分析 AI", "topic_cluster": "investment_commercial", "business_goal": "technical_authority", "priority": "B", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "立地、駅距離、競合、客層を整理し、店舗物件の提案材料にする。"},
    {"topic_id": "topic_070", "master_topic": "売買契約書チェックをAIで補助する方法", "target_keyword": "売買契約書 チェック AI", "topic_cluster": "compliance_support", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "AIを契約書確認の補助として使う考え方と、実務上の注意点を説明する。"},
    {"topic_id": "topic_071", "master_topic": "賃貸契約書の確認ポイントを整理する方法", "target_keyword": "賃貸契約書 確認ポイント", "topic_cluster": "compliance_support", "business_goal": "seo_backlink", "priority": "B", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "特約、原状回復、更新、解約など賃貸契約で確認すべき項目を整理する。"},
    {"topic_id": "topic_072", "master_topic": "賃貸管理のクレーム対応文をAIで作る方法", "target_keyword": "賃貸管理 クレーム対応 文例", "topic_cluster": "operations_support", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "騒音、設備不良、退去、家賃滞納など管理業務の文例を作る。"},
    {"topic_id": "topic_073", "master_topic": "入居者向けお知らせ文をAIで効率化する方法", "target_keyword": "入居者 お知らせ 文例", "topic_cluster": "operations_support", "business_goal": "seo_backlink", "priority": "B", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "点検、工事、更新、注意喚起など入居者向け通知文を標準化する。"},
    {"topic_id": "topic_074", "master_topic": "不動産業務のチェックリストをAIで作る方法", "target_keyword": "不動産 業務 チェックリスト AI", "topic_cluster": "operations_support", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "査定、契約、管理、広告など不動産業務のチェックリストをAIで作る。"},
    {"topic_id": "topic_076", "master_topic": "宅建民法の契約不適合責任をわかりやすく整理", "target_keyword": "宅建 契約不適合責任", "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "買主の権利、通知期間、解除、損害賠償など権利関係の頻出論点を整理する。"},
    {"topic_id": "topic_079", "master_topic": "宅建業法の37条書面を確実に覚える方法", "target_keyword": "宅建 37条書面 覚え方", "topic_cluster": "takken_exam_prep", "business_goal": "seo_backlink", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "35条書面との違い、記載事項、出題パターンを比較して覚える。"},
    {"topic_id": "topic_091", "master_topic": "不動産AIで査定書の説明文を作る方法", "target_keyword": "不動産 査定書 説明文 AI", "topic_cluster": "area_research", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "査定結果、相場根拠、注意点を顧客に伝わる説明文にする。"},
    {"topic_id": "topic_093", "master_topic": "不動産AIで売主向け提案書を作る方法", "target_keyword": "不動産 売主 提案書 AI", "topic_cluster": "property_marketing", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "売却受託のための価格根拠、販売戦略、広告計画を提案書にまとめる。"},
    {"topic_id": "topic_094", "master_topic": "不動産AIで買主向け物件比較表を作る方法", "target_keyword": "不動産 物件比較表 AI", "topic_cluster": "property_marketing", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "複数物件の比較軸、資金計画、生活導線を整理して意思決定を支援する。"},
    {"topic_id": "topic_095", "master_topic": "宅建コーチと不動産AIツールを併用する学習実務ロードマップ", "target_keyword": "宅建コーチ 不動産AI ロードマップ", "topic_cluster": "double_license", "business_goal": "brand_awareness", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "宅建学習から不動産実務AI活用までを一つの成長ロードマップにする。"},
    {"topic_id": "topic_115", "master_topic": "宅建の過去問を解いた後に必ずやる復習チェック", "target_keyword": "宅建 過去問 復習 チェック", "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "過去問を解いた後の復習手順を整理し、AI解説と弱点ノートへつなげる。"},
    {"topic_id": "topic_122", "master_topic": "不動産AIで退去立会いチェックリストを作る方法", "target_keyword": "退去立会い チェックリスト AI", "topic_cluster": "operations_support", "business_goal": "seo_backlink", "priority": "B", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "退去時確認、原状回復、写真記録、見積もり前チェックを整理する。"},
    {"topic_id": "topic_123", "master_topic": "宅建合格者が不動産AIで実務力を伸ばす方法", "target_keyword": "宅建合格者 不動産AI 実務力", "topic_cluster": "double_license", "business_goal": "brand_awareness", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "宅建知識を査定、契約、営業資料作成などの実務AI活用へつなげる。"},
    {"topic_id": "topic_300", "master_topic": "宅建コーチで毎日の学習ログを成果につなげる方法", "target_keyword": "宅建 学習ログ AI管理", "topic_cluster": "takken_exam_prep", "business_goal": "brand_awareness", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "学習時間、正答率、復習履歴を可視化し、翌日の学習内容へ反映する。"},
    {"topic_id": "topic_305", "master_topic": "宅建のAI模試を受けた後の復習手順", "target_keyword": "宅建 AI模試 復習", "topic_cluster": "takken_exam_prep", "business_goal": "brand_awareness", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "模試結果を見て終わらせず、弱点補強と次回演習につなげる手順。"},
    {"topic_id": "topic_307", "master_topic": "宅建のスキマ時間学習をAIで設計する方法", "target_keyword": "宅建 スキマ時間 AI学習", "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "通勤、昼休み、寝る前など短時間学習を一問一答と復習で設計する。"},
    {"topic_id": "topic_309", "master_topic": "不動産AIで売却査定後の提案メールを作る方法", "target_keyword": "売却査定後 提案メール AI", "topic_cluster": "property_marketing", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "査定後のフォロー文、価格根拠、販売戦略提案をメール化する。"},
    {"topic_id": "topic_310", "master_topic": "不動産AIで賃貸募集の改善ポイントを洗い出す方法", "target_keyword": "賃貸募集 改善 AI分析", "topic_cluster": "operations_support", "business_goal": "technical_authority", "priority": "A", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "賃料、写真、設備訴求、広告文を見直し、空室改善へつなげる。"},
    {"topic_id": "topic_400", "master_topic": "宅建コーチで朝5分の確認テストを習慣化する方法", "target_keyword": "宅建 朝5分 確認テスト", "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "短時間でも続けられる確認テスト習慣を作り、毎日の学習継続につなげる。"},
    {"topic_id": "topic_402", "master_topic": "宅建コーチで試験日までの未学習範囲を管理する方法", "target_keyword": "宅建 未学習範囲 管理", "topic_cluster": "takken_exam_prep", "business_goal": "brand_awareness", "priority": "S", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "未着手分野を可視化し、残り日数から優先順位を決める。"},
    {"topic_id": "topic_403", "master_topic": "不動産AIで来店前アンケートを営業資料に変える方法", "target_keyword": "来店前アンケート 営業資料 AI", "topic_cluster": "property_marketing", "business_goal": "technical_authority", "priority": "B", "target_platforms": ["note", "ameba", "hatena"], "status": "ready", "brief": "顧客の事前回答を条件整理、提案物件、資金計画に変換する。"},
    {"topic_id": "topic_500", "master_topic": "宅建コーチで昼休み15分の弱点復習を回す方法", "target_keyword": "宅建 昼休み15分 弱点復習", "topic_cluster": "takken_exam_prep", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "昼休みの短時間学習に絞り、弱点論点と一問一答を組み合わせる。"},
    {"topic_id": "topic_501", "master_topic": "不動産AIで反響後24時間以内の初回返信を作る方法", "target_keyword": "不動産 反響 初回返信 AI", "topic_cluster": "property_marketing", "business_goal": "traffic_reach", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "ポータル反響、資料請求、問い合わせ後の初回返信文をAIで即作成する。"},
    {"topic_id": "topic_502", "master_topic": "宅建学習から不動産DX人材になるためのステップ", "target_keyword": "宅建 不動産DX 人材", "topic_cluster": "double_license", "business_goal": "brand_awareness", "priority": "A", "target_platforms": ["note", "ameba", "x"], "status": "ready", "brief": "宅建コーチと不動産AIツールの両方を訴求するキャリア型テーマ。"},
]


def text(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value or "").strip()


def get_token(client: httpx.Client) -> str:
    response = client.post(
        f"{BASE}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": os.environ["FEISHU_APP_ID"], "app_secret": os.environ["FEISHU_APP_SECRET"]},
    )
    payload = response.json()
    if response.status_code >= 400 or payload.get("code") != 0:
        raise RuntimeError(response.text)
    return str(payload["tenant_access_token"])


def main() -> None:
    with httpx.Client(trust_env=False, timeout=60) as client:
        token = get_token(client)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        records: dict[str, str] = {}
        page_token = ""
        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            response = client.get(
                f"{BASE}/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
                headers=headers,
                params=params,
            )
            payload = response.json()
            if response.status_code >= 400 or payload.get("code") != 0:
                raise RuntimeError(response.text)
            data = payload.get("data", {})
            for item in data.get("items", []):
                topic_id = text((item.get("fields") or {}).get("topic_id"))
                if topic_id:
                    records[topic_id] = str(item.get("record_id") or item.get("id") or "")
            if not data.get("has_more"):
                break
            page_token = str(data.get("page_token") or "")

        all_topics = TOPICS + ADDITIONAL_TOPICS
        updated = []
        missing = []
        for topic in all_topics:
            record_id = records.get(topic["topic_id"])
            if not record_id:
                missing.append(topic["topic_id"])
                continue
            response = client.put(
                f"{BASE}/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{record_id}",
                headers=headers,
                json={"fields": topic},
            )
            payload = response.json()
            if response.status_code >= 400 or payload.get("code") != 0:
                raise RuntimeError(f"{topic['topic_id']} failed: {response.text}")
            updated.append(topic["topic_id"])
        print(json.dumps({"updated_count": len(updated), "missing": missing, "sample": all_topics[0]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

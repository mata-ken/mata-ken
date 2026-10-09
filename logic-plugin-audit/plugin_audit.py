#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Logic Pro プラグイン総点検ツール (plugin_audit.py)

Mac 上で実行すると、以下をすべて自動で調べてレポートを作ります。

  1. インストール済みプラグイン (AU / VST / VST3 / AAX / CLAP) の場所・バージョン・サイズ・対応CPU
  2. 音源ライブラリ (Kontakt / Spectrasonics / Spitfire / EastWest / Toontrack など) の場所と容量
  3. ダウンロードフォルダ等に散らばったインストーラー (.dmg / .pkg / .zip)
  4. 過去の Logic プロジェクト (.logicx) を全部読み、どのプラグインをいつ使ったか
  5. 各プラグインの役割 (ドラム / ベース / ギター / オーケストラ / ボーカル / EQ ...) を自動分類
  6. 整理プラン (Logic のプラグインマネージャ用カテゴリ表・インストーラー整理スクリプト・
     未使用プラグインの退避スクリプト) を生成

このツール自体はファイルを移動・削除しません (読み取り専用)。
整理用のシェルスクリプトを「生成するだけ」で、実行するかどうかはあなたが決めます。

使い方:
    python3 plugin_audit.py              # 標準 (外付けドライブも含めて探す)
    python3 plugin_audit.py --quick      # 外付けドライブ・ライブラリ容量計算を省略して高速に
    python3 plugin_audit.py --help       # そのほかのオプション

Python 3.8 以降の標準ライブラリのみで動きます (追加インストール不要)。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.0.0"

# --------------------------------------------------------------------------------------
# パス関連 (--root はテスト用: 擬似的なファイルシステムを指定できる)
# --------------------------------------------------------------------------------------
ROOT = ""
HOME = Path.home()
START = time.time()


def sp(abs_path: str) -> Path:
    """システム絶対パスを (--root を考慮して) 実パスに変換"""
    if ROOT:
        return Path(ROOT) / abs_path.lstrip("/")
    return Path(abs_path)


def hp(rel: str = "") -> Path:
    """ホームディレクトリ配下のパス"""
    base = sp(str(HOME))
    return base / rel if rel else base


def display_path(p: Path) -> str:
    s = str(p)
    if ROOT and s.startswith(ROOT):
        s = s[len(ROOT.rstrip("/")):] or "/"
    return s


def log(msg: str) -> None:
    el = time.time() - START
    print("[{:02d}:{:02d}] {}".format(int(el // 60), int(el % 60), msg), flush=True)


def human_size(n: float | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return ("{:.0f} {}" if unit in ("B", "KB") else "{:.1f} {}").format(n, unit)
        n /= 1024.0
    return str(n)


def iso(ts: float | None) -> str:
    if not ts:
        return ""
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def norm(s: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", (s or "").lower())


# --------------------------------------------------------------------------------------
# カテゴリ定義 (Logic のプラグインマネージャで作るフォルダ名もここで決める)
# --------------------------------------------------------------------------------------
CATEGORIES = [
    # key,        日本語ラベル,                           Logic プラグインマネージャ用カテゴリ名
    ("drums",     "ドラム・パーカッション",               "01 ドラム・パーカッション"),
    ("bass",      "ベース",                               "02 ベース"),
    ("guitar",    "ギター（音源・アンプ）",               "03 ギター"),
    ("keys",      "ピアノ・鍵盤・オルガン",               "04 ピアノ・鍵盤"),
    ("synth",     "シンセサイザー",                       "05 シンセ"),
    ("orch",      "オーケストラ・シネマティック",         "06 オーケストラ・映画音楽"),
    ("world",     "民族楽器・その他の生楽器",             "07 民族楽器・その他"),
    ("sampler",   "サンプラー・音源プレイヤー",           "08 サンプラー・プレイヤー"),
    ("vocal",     "ボーカル（ピッチ補正・処理・歌声合成）", "09 ボーカル"),
    ("eq",        "EQ・レゾナンス処理",                   "10 EQ"),
    ("dyn",       "コンプ・ダイナミクス",                 "11 コンプ・ダイナミクス"),
    ("sat",       "サチュレーション・歪み・ローファイ",   "12 サチュレーション・歪み"),
    ("verb",      "リバーブ",                             "13 リバーブ"),
    ("delay",     "ディレイ",                             "14 ディレイ"),
    ("mod",       "モジュレーション・空間・クリエイティブFX", "15 モジュレーション・クリエイティブ"),
    ("strip",     "チャンネルストリップ・ミックス総合",   "16 チャンネルストリップ・ミックス"),
    ("master",    "マスタリング・リミッター",             "17 マスタリング"),
    ("restore",   "ノイズ除去・音声修復",                 "18 ノイズ除去・修復"),
    ("util",      "分析・メーター・ユーティリティ",       "19 メーター・ユーティリティ"),
    ("midi",      "MIDI・作曲支援",                       "20 MIDI・作曲支援"),
    ("other_inst", "音源（自動分類できず）",              "98 音源（その他）"),
    ("other_fx",  "エフェクト（自動分類できず）",         "99 エフェクト（その他）"),
]
CAT_LABEL = {k: l for k, l, _ in CATEGORIES}
CAT_LOGIC = {k: g for k, _, g in CATEGORIES}
CAT_ORDER = {k: i for i, (k, _, _) in enumerate(CATEGORIES)}

CAT_DEFAULT_DESC = {
    "drums": "ドラム／パーカッションの音源・処理",
    "bass": "ベースの音源またはベースアンプ",
    "guitar": "ギター音源、またはギターアンプ／エフェクトのシミュレーター",
    "keys": "ピアノ・エレピ・オルガンなど鍵盤楽器の音源",
    "synth": "シンセサイザー音源",
    "orch": "オーケストラ・映画音楽系の音源",
    "world": "民族楽器や各種生楽器の音源",
    "sampler": "サンプル音源を読み込んで鳴らすプレイヤー／サンプラー",
    "vocal": "ボーカル向けの処理（ピッチ補正・ディエッサー等）または歌声合成",
    "eq": "音の周波数バランスを整えるイコライザー",
    "dyn": "音量の強弱を整えるコンプレッサー等",
    "sat": "倍音や歪みを足して音を太く・温かくする",
    "verb": "残響（空間の広がり）を付ける",
    "delay": "やまびこ（反復音）を付ける",
    "mod": "コーラス・フェイザー・フィルター・ステレオ拡張などの音作り系",
    "strip": "EQ・コンプなどが一体になったミックス用チャンネル処理",
    "master": "最終的な音圧・音量を仕上げるマスタリング用",
    "restore": "ノイズ・クリック・反響などを除去する修復ツール",
    "util": "メーター・アナライザー・ゲイン調整・モニター補正など",
    "midi": "コード・メロディ・アルペジオなどの作曲支援／MIDI処理",
    "other_inst": "音源（名前から役割を判定できませんでした）",
    "other_fx": "エフェクト（名前から役割を判定できませんでした）",
}

# 製品ごとのルール (上から順に最初にマッチしたものを採用)
# (正規表現, カテゴリ, 説明)
PRODUCT_RULES: list[tuple[str, str, str]] = [
    # ---- ボーカル -------------------------------------------------------------------
    (r"melodyne", "vocal", "Celemony製。ボーカル等の音程・タイミングを1音ずつ編集できる定番ピッチ補正（ARA対応）"),
    (r"auto-?tune|antares", "vocal", "Antares製。リアルタイムのピッチ補正。ケロケロ効果からナチュラルな補正まで"),
    (r"waves tune|tune real-?time", "vocal", "Waves製のピッチ補正"),
    (r"\bnectar", "vocal", "iZotope製。ボーカル用オールインワン処理（EQ・コンプ・ピッチ・ハモリ等）"),
    (r"vocal ?rider", "vocal", "Waves製。ボーカルの音量を自動で一定に保つ"),
    (r"vocalsynth", "vocal", "iZotope製。ボコーダー・トークボックス等のボーカル変形エフェクト"),
    (r"little ?alter ?boy", "vocal", "Soundtoys製。声の高さ・性別感（フォルマント）を変える"),
    (r"revoice|vocalign|synchro ?arts", "vocal", "Synchro Arts製。ダブルやハモリのタイミング・ピッチを主旋律に揃える"),
    (r"pro-ds|de-?ess|sibilan|\bdess|esser", "vocal", "ディエッサー（歯擦音「サ行」を抑える）"),
    (r"synthesizer ?v|dreamtonics|vocaloid|ace ?studio|emvoice|cevio|\butau|vocalina|vocaloid", "vocal", "歌声合成ソフト（歌詞とメロディから歌声を生成）"),
    (r"exhale|vocal (flow|sampler)", "vocal", "ボーカル素材のサンプル音源"),
    (r"graillon|metatune|gsnap|pitcher\b|mautopitch|pitchproof", "vocal", "ピッチ補正／ボーカルエフェクト"),
    (r"vocal|voice|renaissance ?vox|\bvox\b(?! ?continental)|vocoder|throat|harmony engine|choir ?fx|doubler", "vocal", "ボーカル処理系エフェクト"),
    # ---- ノイズ除去・修復 -----------------------------------------------------------
    (r"\brx\b|\brx ?\d|izotope rx", "restore", "iZotope RX。ノイズ・クリック・反響・リップノイズなどを除去する修復ツール"),
    (r"clarity ?vx|dialogue ?(isolate|match)|goyo|supertone ?clear|unveil|dxrevive|accentize", "restore", "声とノイズ/反響を分離するAI系修復ツール"),
    (r"de-?noise|de-?click|de-?hum|de-?clip|de-?reverb|dereverb|denoise|noise ?reduc|\bwns\b|\bnsk\b|z-noise|x-noise|x-click|x-hum|de-?breath|de-?plosive|mouth ?de", "restore", "ノイズ・クリック・ハム等の除去"),
    # ---- マスタリング ---------------------------------------------------------------
    (r"ozone", "master", "iZotope製。AIアシスタント付きのマスタリング総合スイート"),
    (r"pro-l\b|pro-l ?2", "master", "FabFilter製。透明感の高い定番リミッター"),
    (r"\bl[123](\b|-| |16)|l316|l3-?ll|l3 multi", "master", "Waves製マキシマイザー（音圧上げ）"),
    (r"elevate|invisible ?limiter|weiss|finalizer|t-racks|stealth ?limiter|standard ?clip|kclip|gclip|clipper|maximi[sz]er|bx_limiter|oxford limiter|smart:?limit|limitless|unlimited|limiter|mastering|master ?rig|master ?plan|vintage ?master|landr", "master", "マスタリング／リミッター・クリッパー"),
    # ---- チャンネルストリップ・ミックス総合 -----------------------------------------
    (r"neutron", "strip", "iZotope製。AIアシスタント付きミックス用チャンネルストリップ"),
    (r"scheps ?omni|omni ?channel", "strip", "Waves製。Andrew Scheps監修の多機能チャンネルストリップ"),
    (r"cla ?mixhub|cla ?mix|mixcentric", "strip", "ミックス総合（チャンネルストリップ）"),
    (r"channel ?strip|e-channel|g-channel|4k ?[beg]|ssl ?(4000|native|e |g |channel)|ssl e|ssl g|\bvcc\b|virtual console|console ?1|bx_console|lindell|harrison ?32c|\b32c\b|\bn ?4k\b|api ?vision|v-?series|britson|ns1|neve ?v|amek ?9099|dual ?channel ?strip|\bconsole", "strip", "アナログ卓を再現したチャンネルストリップ"),
    # ---- EQ -----------------------------------------------------------------------
    (r"pro-q", "eq", "FabFilter製。ダイナミックEQ対応の超定番イコライザー"),
    (r"soothe|smooth ?operator|resonance ?suppress|gullfoss|spiff", "eq", "耳障りな共振（キンキン・こもり）を自動で抑える"),
    (r"pultec|eqp-?1a|meq-?5|\b1073\b|\b1084\b|api ?5[56]0|passeq|massive ?passive|kirchhoff|tdr ?nova|slick ?eq|renaissance ?eq|\bq10\b|f6\b|curve ?eq|tilt ?eq|maag|sonible ?(smart:)?eq|smart:?eq|equaliz|\beq\b|eq\d|\b(?!freq\b|pianoteq\b)[a-z]+eq\b|dyn ?eq", "eq", "イコライザー（音の周波数バランスを整える）"),
    # ---- ディレイ (sat より先: tape echo 等) -----------------------------------------
    (r"echoboy", "delay", "Soundtoys製。テープ／アナログ系の名作ディレイ"),
    (r"valhalla ?delay|timeless|h-?delay|replika|dubstation|space ?echo|re-?201|tape ?echo|super ?tap|super ?delay|tube ?delay|primal ?tap|pro-?d\b|echo|delay", "delay", "ディレイ（反復音）"),
    # ---- リバーブ -----------------------------------------------------------------
    (r"valhalla", "verb", "Valhalla DSP製。コスパ最強クラスのリバーブ"),
    (r"pro-?r\b|pro-?r ?2", "verb", "FabFilter製。自然で扱いやすいリバーブ"),
    (r"altiverb|space ?designer|chromaverb|blackhole|h-?reverb|r-?verb|trueverb|abbey ?road ?(chambers|plates)|cinematic ?rooms|raum|lexicon|pcm ?native|bricasti|seventh ?heaven|7th ?heaven|lustrous ?plates|cloud ?seed|aether|verberate|little ?plate|supermassive|shimmer|reverb|verb\b|plate\b|chamber|convolution|\bir[- ]?\d|\bhall\b|\broom\b", "verb", "リバーブ（残響・空間）"),
    # ---- コンプ・ダイナミクス -----------------------------------------------------
    (r"pro-c\b|pro-c ?2|pro-mb|pro-g\b", "dyn", "FabFilter製のダイナミクス系（コンプ/マルチバンド/ゲート）"),
    (r"1176|la-?2a|la-?3a|cla-?2a|cla-?3a|cla-?76|fairchild|distressor|\bvca\b|opto|bus ?comp|glue|vari-?mu|33609|shadow ?hills|cl ?1b|api ?2500|elysia|mpressor|townhouse|smasher|kotelnikov|\bc[46]\b|rcomp|\bmv2\b|leveler|bass ?rider|transient|trans-?x|smack|\bgate\b|expander|multiband|compress|comp\b|\bdyn|dynamic", "dyn", "コンプレッサー等のダイナミクス処理"),
    # ---- サチュレーション ---------------------------------------------------------
    (r"decapitator", "sat", "Soundtoys製。アナログ機材系の定番サチュレーター"),
    (r"saturn", "sat", "FabFilter製。マルチバンド対応のサチュレーター"),
    (r"rc-?20|retro ?color|lo-?fi|vinyl|cassette|sketchcassette|bitcrush|crusher", "sat", "ローファイ化（レコード・カセット風の質感）"),
    (r"satur|tape|j37|kramer|ampex|studer|crushstation|devil-?loc|radiator|trash|distort|overdrive|fuzz|\btube\b|warmth|heat\b|exciter|aphex|vitamin|maxxbass|harmonic|culture ?vulture|thermionic|sausage|fattener|drive\b|kush|clip ?shifter|black ?box", "sat", "サチュレーション・歪み（倍音で太さ・温かみを足す）"),
    # ---- 名前に drum/beat 等を含むクリエイティブ系を先に確定 ------------------------
    (r"gross ?beat|shaperbox|effectrix|beat ?repeat|stutter ?edit|lfo ?tool|volumeshaper|output ?portal|\bportal\b|thermal|polychrome|turnado", "mod", "リズムに合わせて音を刻む・揺らす・グリッチさせるクリエイティブ系エフェクト"),
    # ---- ギター (アンプ・エフェクトも含む) ----------------------------------------
    (r"guitar ?rig", "guitar", "Native Instruments製。ギターアンプ・エフェクトのシミュレーター"),
    (r"amplitube", "guitar", "IK Multimedia製。ギター/ベースのアンプ・エフェクトのシミュレーター"),
    (r"bias ?(fx|amp|pedal)|positive ?grid", "guitar", "Positive Grid製。ギターアンプ・エフェクトのシミュレーター"),
    (r"helix ?native|line ?6", "guitar", "Line 6製。Helixのアンプ／エフェクトモデリング"),
    (r"archetype|neural ?dsp|parallax|fortin|soldano|gojira|plini|nolly|cory ?wong|petrucci|tone ?king|rabea|tim ?henson|abasi|morgan ?amps|mesa ?boogie|nameless|quad ?cortex|darkglass ?ultra", "guitar", "Neural DSP製。高品位なギターアンプ・シミュレーター（Archetypeシリーズ）"),
    (r"tonex|neural ?amp ?modeler|\bnam\b|tonehub|stl ?(tones|ignite)|th-?u\b|overloud|kuassa|mercuriall|joey ?sturgis|ignite ?amps|\btse\b|lepou|torpedo|two ?notes|genome|ir ?loader|nadir|cab ?(lab|sim)|amp ?sim|\bamp\b|pedal", "guitar", "ギターアンプ・キャビネット・エフェクトのシミュレーター"),
    (r"shreddage|impact ?soundworks", "guitar", "Impact Soundworks製。リアルなギター音源（メタル・ロック向け）"),
    (r"ample ?(guitar|gibson|martin|taylor|fender|ethno|metal|strat|tele|bass)|ample ?sound", "guitar", "Ample Sound製。リアルなギター（ベース）音源"),
    (r"electri6ity|electric ?sunburst|real ?(guitar|strat|lpc|eight)|musiclab", "guitar", "リアルなギター音源（打ち込み用）"),
    (r"virtual ?guitarist|ujam.*(guitar|iron|amber|carbon|sparkle|silk|electro)", "guitar", "UJAM製。ワンキーで弾けるギター演奏音源"),
    (r"guitar|acoustic ?gtr|\bstrum", "guitar", "ギター音源・処理"),
    # ---- ドラム -------------------------------------------------------------------
    (r"superior ?drummer", "drums", "Toontrack製。マルチマイクの本格アコースティックドラム音源。作り込み派向け"),
    (r"ezdrummer|ez ?drummer", "drums", "Toontrack製。手軽なドラム音源。ジャンル別キットとグルーヴ集ですぐ打ち込める"),
    (r"addictive ?drums", "drums", "XLN Audio製。プリセットの完成度が高いドラム音源"),
    (r"\bbfd", "drums", "BFD製。高解像度のアコースティックドラム音源"),
    (r"steven ?slate ?drums|\bssd ?\d|slate ?drums|trigger ?2", "drums", "Steven Slate製。ロック/メタル向けのパンチあるドラム音源"),
    (r"getgood|\bggd\b|one ?kit ?wonder", "drums", "GetGood Drums。モダンロック/メタル向けドラム音源"),
    (r"battery", "drums", "Native Instruments製。ドラムサンプラー（エレクトロ系キット作りに最適）"),
    (r"\bxo\b|xln ?audio ?xo", "drums", "XLN Audio製。ワンショットのドラムサンプル整理＆ビートメイク"),
    (r"maschine", "drums", "Native Instruments製。ビートメイク用グルーヴボックス"),
    (r"groove ?agent", "drums", "Steinberg製ドラム音源"),
    (r"virtual ?drummer|ujam.*(drum|beatmaker)|beatmaker", "drums", "UJAM製。ワンキーで鳴らせるドラム演奏音源"),
    (r"microtonic|punchbox|kick ?\d|\bkick\b|tremor|nerve|drum ?synth|tr-?\d0\d|tr-?8|808|909|drum|percussion|\bperc\b|snare|cymbal|\btoms?\b|taiko|beat\b|breaks?", "drums", "ドラム／パーカッション音源・処理"),
    # ---- ベース -------------------------------------------------------------------
    (r"trilian", "bass", "Spectrasonics製。エレキ・アコースティック・シンセベースの定番音源"),
    (r"scarbee", "bass", "Native Instruments製。リアルなエレキベース音源"),
    (r"modo ?bass", "bass", "IK Multimedia製。物理モデリングのエレキベース音源"),
    (r"ezbass|ez ?bass", "bass", "Toontrack製。手軽なベース音源（グルーヴ集付き）"),
    (r"virtual ?bassist|ujam.*(bass|dandy|mellow|royal|rowdy)", "bass", "UJAM製。ワンキーで弾けるベース音源"),
    (r"darkglass|ampeg|\bsvt\b|bass ?amp|\bbass\b|808 ?bass|sub ?bass", "bass", "ベース音源・ベースアンプ"),
    # ---- ピアノ・鍵盤 -------------------------------------------------------------
    (r"keyscape", "keys", "Spectrasonics製。最高峰クラスのピアノ／鍵盤コレクション"),
    (r"pianoteq|modartt", "keys", "Modartt製。物理モデリングで軽量なピアノ音源"),
    (r"noire|the ?grandeur|the ?gentleman|the ?giant|una ?corda|alicia'?s? ?keys|maverick|definitive ?piano", "keys", "Native Instruments製のピアノ音源"),
    (r"ravenscroft|ivory|garritan ?cfx|ezkeys|ez ?keys|addictive ?keys|ilya ?efimov|keys ?of|piano|grand\b|upright", "keys", "ピアノ音源"),
    (r"rhodes|wurli|e-?piano|epiano|lounge ?lizard|mark ?i\b|stage-?73|clav|organ|b-?3|hammond|vintage ?organs|farfisa|vox ?continental|harpsichord|celesta|mellotron|\bkeys\b", "keys", "エレピ・オルガン・鍵盤楽器の音源"),
    # ---- オーケストラ・シネマティック ---------------------------------------------
    (r"\blabs\b", "sampler", "Spitfire Audio製。無料の多ジャンル音源集（ピアノ・ストリングス・シンセ等）"),
    (r"bbc ?symphony", "orch", "Spitfire Audio製。BBC交響楽団を収録したフルオーケストラ音源"),
    (r"albion", "orch", "Spitfire Audio製。映画音楽向けのオーケストラ音源"),
    (r"spitfire|originals|abbey ?road ?one|studio ?(strings|brass|woodwinds|orchestra)|symphonic ?motions|appassionata", "orch", "Spitfire Audio製オーケストラ／シネマティック音源"),
    (r"opus|hollywood ?(strings|brass|orchestra|choirs|percussion|woodwinds)|symphonic ?orchestra|eastwest|east ?west|\bplay\b", "orch", "EastWest製オーケストラ音源（Opus/Play）"),
    (r"cinematic ?studio|\bcss\b|\bcsb\b|\bcsw\b|\bcss\b", "orch", "Cinematic Studio Series。表現力の高いオーケストラ音源"),
    (r"orchestral ?tools|sine ?player|\bsine\b|berlin ?(strings|brass|woodwinds|percussion|orchestra)|metropolis ?ark|tallinn|miroire", "orch", "Orchestral Tools製オーケストラ音源（SINEプレイヤー）"),
    (r"vsl|vienna|synchron", "orch", "Vienna Symphonic Library製の本格オーケストラ音源"),
    (r"cinesamples|cineperc|cinestrings|cinebrass|cinewinds|8dio|audio ?imperia|heavyocity|gravity|sonuscore|action ?strikes|rise ?& ?hit|session ?strings|symphony ?series|orchestra|orchestral|strings|brass|woodwind|choir|cinematic|symphon|trailer|\bepic\b", "orch", "オーケストラ／映画音楽系の音源"),
    # ---- サンプラー・プレイヤー ---------------------------------------------------
    (r"kontakt", "sampler", "Native Instruments製。サンプル音源の定番プレイヤー（大量の音源ライブラリをこれで鳴らす）"),
    (r"komplete ?kontrol", "sampler", "Native Instruments製。KOMPLETE音源をまとめて扱うブラウザ兼ホスト"),
    (r"falcon|uvi ?workstation|\buvi\b", "sampler", "UVI製のサンプラー／音源プレイヤー"),
    (r"halion|sforzando|decent ?sampler|engine ?2|best ?service ?engine|kontakt ?player|arcade|output ?arcade|splice ?instrument|astra|sampler|rompler", "sampler", "サンプラー・音源プレイヤー"),
    # ---- シンセ -------------------------------------------------------------------
    (r"omnisphere", "synth", "Spectrasonics製。膨大な音色を持つ定番シンセ（パッド・テクスチャが強い）"),
    (r"serum", "synth", "Xfer Records製。EDMで定番のウェーブテーブル・シンセ"),
    (r"vital", "synth", "Vital Audio製。高機能なウェーブテーブル・シンセ"),
    (r"massive", "synth", "Native Instruments製。ベース・リードが得意なシンセ"),
    (r"diva", "synth", "u-he製。アナログ・シンセの音を忠実に再現"),
    (r"pigments", "synth", "Arturia製。多方式の音源を組み合わせられるシンセ"),
    (r"sylenth|spire|hive|repro|zebra|phase ?plant|nexus|electra|avenger|synthmaster|dune|obxd|dexed|surge|\btal-|absynth|fm8|reaktor|razor|monark|super ?8|synplant|analog ?lab|\bmini ?v\d?\b|jup-?8|prophet|cs-?80|dx7|ob-?x|jun-?6|cmi ?v|synclavier|buchla|modular|\bsem\b|matrix-?12|emulator|augmented|minimoog|moog|model ?d|model ?15|mariana|animoog|korg|ms-?20|polysix|wavestation|triton|opsix|wavestate|modwave|jupiter|juno|jx-|sh-?101|roland|cherry ?audio|dreamsynth|mercury-?4|voltage ?modular|synth|wavetable|\bosc\b", "synth", "シンセサイザー"),
    # ---- 民族楽器・その他 ---------------------------------------------------------
    (r"koto|shamisen|shakuhachi|erhu|sitar|tabla|\boud\b|duduk|bagpipe|ethno|\bworld\b|ethnic|kalimba|marimba|vibraphone|\bharp\b|ukulele|banjo|mandolin|accordion|harmonica|sax|trumpet|flute|violin|cello", "world", "民族楽器・各種生楽器の音源"),
    # ---- モジュレーション・空間・クリエイティブ -----------------------------------
    (r"shaperbox|lfo ?tool|volumeshaper|cableguys|kickstart|portal|output ?movement|movement|thermal|polychrome|effectrix|gross ?beat|turnado|driver|stutter|glitch|fracture|granul|crystallizer|microshift|h3000|eventide|harmonizer|pitch ?shift|chorus|flang|phase[rd]|tremolo|vibrato|rotary|leslie|filter|panman|wider|stereo|width|imager|spatial|dimension|ensemble|ring ?mod|freq ?shift|creative|fx ?rack|panner|autopan|\bott\b", "mod", "モジュレーション・フィルター・ステレオ拡張などの音作り系"),
    # ---- 分析・ユーティリティ -----------------------------------------------------
    (r"insight|\bspan\b|meter|analy[sz]|tonal ?balance|youlean|loudness|levels|metric ?ab|reference|adptr|correlation|scope|tuner|\bgain\b|utility|\btrim\b|\bphase\b|\bmono\b|sidechain|routing|blue ?cat|patchwork|plugindoctor|sonarworks|soundid|realphones|room ?correction|monitor|headphone|\bcans\b|studio ?3|\bnx\b|ocean ?way|virtual ?mix ?room|\bvmr\b|test ?tone|oscillator|signal", "util", "分析・メーター・ユーティリティ系"),
    # ---- MIDI・作曲支援 -----------------------------------------------------------
    (r"scaler|captain|cthulhu|chord|arpeggi|\barp\b|midi|instachord|ripchord|melody ?sauce|orb ?composer|hookpad|riffer|euclid|stepic|bluarp|unison|melodic|songwriting|composer", "midi", "コード・メロディ・アルペジオ等の作曲支援／MIDI処理"),
]
PRODUCT_RULES_C = [(re.compile(p, re.I), c, d) for p, c, d in PRODUCT_RULES]

# 名前だけで検索すると誤検出しやすい一般名 (Logic 内蔵プラグインと被るものなど)
GENERIC_NAMES = {
    "compressor", "reverb", "delay", "eq", "equalizer", "limiter", "gate", "chorus",
    "flanger", "phaser", "tremolo", "filter", "distortion", "overdrive", "saturation",
    "sampler", "synth", "bass", "drums", "piano", "strings", "tape", "echo", "plate",
    "room", "hall", "utility", "gain", "meter", "tuner", "vocoder", "exciter", "stereo",
    "mono", "width", "pan", "panner", "bus", "master", "channel", "console", "drive",
    "vintage", "classic", "studio", "pro", "lite", "free", "plugin", "plug-in", "instrument",
    "effect", "fx", "kit", "default", "space", "air", "glue", "clip", "clipper", "deesser",
    "de-esser", "doubler", "transient", "multiband", "dynamics", "imager", "analyzer",
}

KNOWN_VENDORS = [
    "fabfilter", "waves", "izotope", "native instruments", "spitfire", "eastwest", "east west",
    "toontrack", "xln", "arturia", "u-he", "xfer", "spectrasonics", "soundtoys", "valhalla",
    "plugin alliance", "brainworx", "universal audio", "uad", "slate", "ssl", "solid state logic",
    "softube", "kilohearts", "output", "heavyocity", "ujam", "orchestral tools", "vsl", "vienna",
    "cinesamples", "8dio", "celemony", "antares", "synchro arts", "eventide", "tokyo dawn", "tdr",
    "oeksound", "sonible", "sonnox", "mcdsp", "liquidsonics", "audio damage", "d16", "baby audio",
    "cableguys", "minimal audio", "vital", "neural dsp", "positive grid", "ik multimedia",
    "line 6", "stl tones", "overloud", "kuassa", "ample sound", "musiclab", "modartt",
    "garritan", "embertone", "audio imperia", "sonuscore", "best service", "sample logic",
    "splice", "landr", "unfiltered audio", "goodhertz", "klevgrand", "polyverse", "venomode",
    "korg", "roland", "moog", "cherry audio", "steinberg", "plugin boutique", "scaler",
    "mixed in key", "sonarworks", "nugen", "youlean", "voxengo", "melda", "acustica",
    "nomad factory", "kush", "black rooster", "lindell", "analog obsession", "airwindows",
    "tal", "dreamtonics", "yamaha", "audiomodern", "sound particles", "zynaptiq", "accusonus",
    "accentize", "acon", "krotos", "boom", "uvi", "impact soundworks", "orange tree", "audiority",
    "black octopus", "loopmasters", "sonic academy", "rob papen", "reveal sound", "lennar",
    "refx", "image-line", "xils", "dmg audio", "pulsar", "kiive", "tone empire", "fuse audio",
    "wavesfactory", "denise", "hornet", "credland", "audified", "techivation", "newfangled",
    "kazrog", "bettermaker", "chandler", "manley", "api", "neve", "maag", "shadow hills",
]


# --------------------------------------------------------------------------------------
# ヘルパー
# --------------------------------------------------------------------------------------
def read_plist(path: Path):
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except Exception:
        return None


def read_json_lenient(path: Path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
        txt = re.sub(r",\s*([}\]])", r"\1", txt)  # 末尾カンマ対策 (moduleinfo.json は JSON5 寄り)
        return json.loads(txt)
    except Exception:
        return None


def dir_size(path: Path, timeout: int = 300) -> int | None:
    """フォルダの容量。macOS では du を使う (速い)"""
    try:
        if shutil.which("du"):
            out = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=timeout)
            first = out.stdout.strip().split("\t")[0] if out.stdout else ""
            if first.isdigit():
                return int(first) * 1024
    except Exception:
        pass
    total = 0
    try:
        for dp, _dn, fns in os.walk(path):
            for fn in fns:
                try:
                    total += os.lstat(os.path.join(dp, fn)).st_size
                except OSError:
                    pass
    except Exception:
        return None
    return total


def fourcc_str(v) -> str:
    if isinstance(v, int):
        try:
            return v.to_bytes(4, "big").decode("latin-1")
        except Exception:
            return ""
    return str(v or "")


CPU = {0x01000007: "Intel", 0x0100000C: "Apple Silicon", 7: "Intel(32bit)", 0x0200000C: "Apple Silicon(arm64_32)"}


def bundle_archs(bundle: Path, info: dict | None) -> str:
    exe = (info or {}).get("CFBundleExecutable")
    cand = []
    if exe:
        cand.append(bundle / "Contents" / "MacOS" / exe)
    macos = bundle / "Contents" / "MacOS"
    if macos.is_dir():
        try:
            cand += [p for p in macos.iterdir() if p.is_file()]
        except OSError:
            pass
    for exe_path in cand:
        try:
            with open(exe_path, "rb") as f:
                b = f.read(4096)
        except OSError:
            continue
        if len(b) < 8:
            continue
        magic = int.from_bytes(b[:4], "big")
        archs = []
        if magic in (0xCAFEBABE, 0xCAFEBABF):
            n = int.from_bytes(b[4:8], "big")
            step = 20 if magic == 0xCAFEBABE else 32
            for i in range(min(n, 8)):
                off = 8 + i * step
                ct = int.from_bytes(b[off:off + 4], "big")
                archs.append(CPU.get(ct, hex(ct)))
        elif magic in (0xCFFAEDFE, 0xCEFAEDFE):
            ct = int.from_bytes(b[4:8], "little")
            archs.append(CPU.get(ct, hex(ct)))
        elif magic in (0xFEEDFACF, 0xFEEDFACE):
            ct = int.from_bytes(b[4:8], "big")
            archs.append(CPU.get(ct, hex(ct)))
        if archs:
            uniq = []
            for a in archs:
                if a not in uniq:
                    uniq.append(a)
            return " + ".join(uniq)
    return "不明"


def vendor_from_bundle_id(bid: str) -> str:
    parts = (bid or "").split(".")
    if len(parts) >= 2 and parts[0] in ("com", "net", "org", "de", "fr", "uk", "co", "io", "audio", "jp", "se", "nl", "ch", "it", "at", "dk", "ru", "pl", "ca", "us", "eu"):
        return parts[1]
    return parts[0] if parts and parts[0] else ""


VENDOR_PRETTY = {
    "fabfilter": "FabFilter", "waves": "Waves", "izotope": "iZotope", "native-instruments": "Native Instruments",
    "nativeinstruments": "Native Instruments", "spitfireaudio": "Spitfire Audio", "toontrack": "Toontrack",
    "xlnaudio": "XLN Audio", "arturia": "Arturia", "u-he": "u-he", "xferrecords": "Xfer Records",
    "spectrasonics": "Spectrasonics", "soundtoys": "Soundtoys", "valhalladsp": "Valhalla DSP",
    "plugin-alliance": "Plugin Alliance", "uaudio": "Universal Audio", "softube": "Softube",
    "celemony": "Celemony", "antares": "Antares", "eventide": "Eventide", "ikmultimedia": "IK Multimedia",
    "neuraldsp": "Neural DSP", "positivegrid": "Positive Grid", "eastwest": "EastWest", "ujam": "UJAM",
    "orchestraltools": "Orchestral Tools", "kilohearts": "Kilohearts", "outputsound": "Output",
}


VENDOR_PRETTY.update({"izotope": "iZotope", "u-he": "u-he", "xln": "XLN Audio", "uad": "UAD", "ssl": "SSL",
                      "tdr": "TDR", "vsl": "VSL", "ik multimedia": "IK Multimedia", "d16": "D16", "8dio": "8Dio",
                      "dmg audio": "DMG Audio", "image-line": "Image-Line", "stl tones": "STL Tones",
                      "xfer": "Xfer Records", "uvi": "UVI", "api": "API", "tal": "TAL", "fabfilter": "FabFilter"})


def pretty_vendor(v: str) -> str:
    k = (v or "").lower()
    return VENDOR_PRETTY.get(k) or VENDOR_PRETTY.get(k.replace(" ", "")) or v


# --------------------------------------------------------------------------------------
# 1. プラグイン本体のスキャン
# --------------------------------------------------------------------------------------
PLUGIN_LOCATIONS = [
    ("AU", "Library/Audio/Plug-Ins/Components", ".component"),
    ("VST", "Library/Audio/Plug-Ins/VST", ".vst"),
    ("VST3", "Library/Audio/Plug-Ins/VST3", ".vst3"),
    ("CLAP", "Library/Audio/Plug-Ins/CLAP", ".clap"),
    ("AAX", "Library/Application Support/Avid/Audio/Plug-Ins", ".aaxplugin"),
]
AU_TYPES = {"aumu": "音源", "aufx": "エフェクト", "aumf": "エフェクト(MIDI入力付)", "aumi": "MIDIエフェクト",
            "augn": "ジェネレーター", "aufc": "フォーマット変換", "auol": "オフライン", "aupn": "パンナー", "aumx": "ミキサー"}


def find_bundles(base: Path, ext: str):
    if not base.is_dir():
        return
    for dp, dns, _fns in os.walk(base):
        keep = []
        for d in dns:
            dl = d.lower()
            if dl.endswith(ext):
                yield Path(dp) / d
            elif not dl.endswith((".component", ".vst", ".vst3", ".clap", ".aaxplugin", ".bundle", ".app", ".framework")):
                keep.append(d)  # メーカー名のサブフォルダなどは中まで探す
        dns[:] = keep


def scan_plugins() -> list[dict]:
    rows = []
    for fmt, rel, ext in PLUGIN_LOCATIONS:
        for scope, base in (("システム全体", sp("/" + rel)), ("ユーザー", hp(rel))):
            for b in find_bundles(base, ext):
                info = read_plist(b / "Contents" / "Info.plist") or {}
                bid = info.get("CFBundleIdentifier", "")
                ver = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or ""
                try:
                    mtime = b.stat().st_mtime
                except OSError:
                    mtime = None
                size = dir_size(b, timeout=60)
                arch = bundle_archs(b, info)
                stem = b.name[: -len(ext)]
                base_row = dict(format=fmt, scope=scope, path=display_path(b), bundle=b.name, bundle_id=bid,
                                version=str(ver), size=size or 0, installed=iso(mtime), installed_ts=mtime or 0,
                                arch=arch, au_type="", au_subtype="", au_manu="", vst3_subcats="")
                comps = info.get("AudioComponents") if fmt == "AU" else None
                if comps:
                    for c in comps:
                        full = c.get("name", stem)
                        vendor, name = (full.split(":", 1) + [""])[:2] if ":" in full else ("", full)
                        r = dict(base_row)
                        r.update(vendor=pretty_vendor(vendor.strip() or vendor_from_bundle_id(bid)),
                                 name=name.strip() or stem, au_full_name=full,
                                 au_type=fourcc_str(c.get("type")), au_subtype=fourcc_str(c.get("subtype")),
                                 au_manu=fourcc_str(c.get("manufacturer")))
                        rows.append(r)
                    continue
                vendor = ""
                subcats = ""
                if fmt == "VST3":
                    mi = read_json_lenient(b / "Contents" / "Resources" / "moduleinfo.json") or read_json_lenient(b / "Contents" / "moduleinfo.json")
                    if isinstance(mi, dict):
                        vendor = (mi.get("Factory Info") or {}).get("Vendor", "") or ""
                        cats = []
                        for cl in mi.get("Classes") or []:
                            if isinstance(cl, dict) and cl.get("Category") == "Audio Module Class":
                                cats += cl.get("Sub Categories") or []
                        subcats = "|".join(dict.fromkeys(cats))
                if not vendor:
                    vendor = vendor_from_bundle_id(bid) or (info.get("CFBundleGetInfoString", "") or "").split(" ")[0]
                vendor = pretty_vendor(vendor)
                name = stem
                if vendor and norm(stem).startswith(norm(vendor)) and len(norm(stem)) > len(norm(vendor)) + 1:
                    name = re.sub(r"^" + re.escape(vendor) + r"[\s_\-:]*", "", stem, flags=re.I) or stem
                r = dict(base_row)
                r.update(vendor=vendor, name=name, au_full_name="", vst3_subcats=subcats)
                rows.append(r)
    return rows


def product_key(name: str) -> str:
    n = (name or "").lower()
    n = re.sub(r"\((mono|stereo|m|s|m/s|mono/stereo|stereo/mono|surround|5\.1|7\.1)\)", "", n)
    n = re.sub(r"\b(mono|stereo|m2s|s2s|m/s|x64|64-?bit|vst3?|au|aax)\b", "", n)
    return norm(n)


def classify(prod: dict) -> tuple[str, str, str]:
    """(カテゴリkey, 説明, 判定根拠)"""
    hay = " ".join([prod["vendor"], prod["name"], prod.get("bundle", ""), prod.get("au_full_name", "")]).lower()
    for rx, cat, desc in PRODUCT_RULES_C:
        if rx.search(prod["name"]):
            return cat, desc, "製品名"
    for rx, cat, desc in PRODUCT_RULES_C:
        if rx.search(hay):
            return cat, desc, "メーカー/ファイル名"
    sub = (prod.get("vst3_subcats") or "").lower()
    if sub:
        m = [("drum", "drums"), ("piano", "keys"), ("synth", "synth"), ("sampler", "sampler"), ("eq", "eq"),
             ("dynamics", "dyn"), ("reverb", "verb"), ("delay", "delay"), ("distortion", "sat"),
             ("modulation", "mod"), ("restoration", "restore"), ("mastering", "master"),
             ("analyzer", "util"), ("tools", "util"), ("spatial", "mod"), ("pitch shift", "vocal"),
             ("filter", "mod"), ("instrument", "other_inst"), ("fx", "other_fx")]
        for k, c in m:
            if k in sub:
                return c, CAT_DEFAULT_DESC[c], "VST3の自己申告カテゴリ"
    t = prod.get("au_type", "")
    if t == "aumi":
        return "midi", CAT_DEFAULT_DESC["midi"], "AUの種類"
    if t == "aumu":
        return "other_inst", CAT_DEFAULT_DESC["other_inst"], "AUの種類"
    return "other_fx", CAT_DEFAULT_DESC["other_fx"], "判定できず"


def group_products(rows: list[dict]) -> list[dict]:
    prods: dict[str, dict] = {}
    for r in rows:
        pk = product_key(r["name"])
        # 名前が十分ユニークならメーカー表記の揺れ (AU と VST3 で違う等) を無視してまとめる
        key = pk if len(pk) >= 6 and r["name"].lower() not in GENERIC_NAMES else norm(r["vendor"]) + "/" + pk
        p = prods.get(key)
        if not p:
            p = dict(key=key, vendor=r["vendor"], name=re.sub(r"\s*\((mono|stereo|m|s)\)\s*$", "", r["name"], flags=re.I).strip(),
                     formats=[], paths=[], versions=[], size=0, installed_ts=0, arch=set(),
                     au_names=set(), codes=set(), au_type="", bundle=r["bundle"], au_full_name=r.get("au_full_name", ""),
                     vst3_subcats="", variants=set())
            prods[key] = p
        if r["format"] not in p["formats"]:
            p["formats"].append(r["format"])
        if r["path"] not in p["paths"]:
            p["paths"].append(r["path"])
            p["size"] += r["size"] or 0
        if r["version"] and r["version"] not in p["versions"]:
            p["versions"].append(r["version"])
        p["installed_ts"] = max(p["installed_ts"], r["installed_ts"] or 0)
        if r["format"] in ("AU", "VST", "VST3", "CLAP") and r["arch"]:
            p["arch"].add(r["arch"])
        if r.get("au_full_name"):
            p["au_names"].add(r["au_full_name"])
        if r["au_subtype"] and r["au_manu"]:
            p["codes"].add((r["au_type"], r["au_subtype"], r["au_manu"]))
        if r["au_type"] and not p["au_type"]:
            p["au_type"] = r["au_type"]
        if r["vst3_subcats"]:
            p["vst3_subcats"] = r["vst3_subcats"]
        p["variants"].add(r["name"])
    out = []
    order = {"AU": 0, "VST3": 1, "VST": 2, "CLAP": 3, "AAX": 4}
    for p in prods.values():
        p["formats"].sort(key=lambda f: order.get(f, 9))
        cat, desc, why = classify(p)
        p["category"], p["desc"], p["category_reason"] = cat, desc, why
        p["kind"] = "音源" if p["au_type"] == "aumu" or cat in ("drums", "bass", "keys", "synth", "orch", "world", "sampler", "other_inst") and p["au_type"] in ("", "aumu") else (AU_TYPES.get(p["au_type"], "エフェクト") if p["au_type"] else "不明(VST/AAXのみ)")
        archs = " / ".join(sorted(p["arch"]))
        p["arch"] = archs
        p["intel_only"] = bool(archs) and "Apple Silicon" not in archs and "不明" not in archs
        p["logic_usable"] = "AU" in p["formats"]
        p["installed"] = iso(p["installed_ts"])
        out.append(p)
    return out


# --------------------------------------------------------------------------------------
# 2. ファイルシステム一括探索 (プロジェクト / 音源ライブラリ / インストーラー)
# --------------------------------------------------------------------------------------
PROJECT_EXTS = (".logicx", ".logic")
INSTALLER_EXTS = (".dmg", ".pkg", ".mpkg", ".zip", ".rar", ".7z", ".iso")
SAMPLE_EXTS = (".nki", ".nkx", ".nkc", ".ncw", ".nkr", ".nkm", ".nicnt", ".exs", ".sfz", ".sf2", ".ufs", ".ewi", ".nkb")
LIB_MARKERS = (".nicnt", ".ewi", ".ufs")
KNOWN_LIB_DIRS = {
    "steam": "Spectrasonics (Omnisphere/Keyscape/Trilian)", "toontrack": "Toontrack",
    "spitfire audio": "Spitfire Audio", "spitfire": "Spitfire Audio", "eastwest": "EastWest", "east west": "EastWest",
    "orchestral tools": "Orchestral Tools", "ujam": "UJAM", "native instruments": "Native Instruments",
    "kontakt libraries": "Kontakt ライブラリ", "sample libraries": "サンプルライブラリ", "samples": "サンプル",
    "vienna": "VSL", "vsl": "VSL", "cinesamples": "Cinesamples", "8dio": "8Dio", "heavyocity": "Heavyocity",
    "uvi": "UVI", "soundbanks": "UVI SoundBanks", "arturia": "Arturia",
    "xln audio": "XLN Audio", "addictive drums": "XLN Audio", "superior drummer": "Toontrack",
    "splice": "Splice", "ik multimedia": "IK Multimedia", "slate digital": "Slate Digital",
    "garritan": "Garritan", "best service": "Best Service", "impact soundworks": "Impact Soundworks",
    "audio imperia": "Audio Imperia", "sonuscore": "Sonuscore", "cinematic studio series": "Cinematic Studio",
    "omnisphere": "Spectrasonics", "keyscape": "Spectrasonics",
    "modartt": "Modartt (Pianoteq)", "loopmasters": "Loopmasters", "native access": "Native Instruments",
}
SKIP_DIR_NAMES = {".trash", ".trashes", ".spotlight-v100", ".fseventsd", "node_modules", ".git",
                  "caches", "cache", "logs", ".documentrevisions-v100", ".temporaryitems", "photos library.photoslibrary",
                  "apple", "mobilesync", "containers", "group containers", "metadata", "developer", "xcode",
                  "system", "coresimulator", "backups.backupdb", "private", "bin", "sbin", "usr"}
PACKAGE_SUFFIXES = (".app", ".component", ".vst", ".vst3", ".aaxplugin", ".clap", ".framework", ".bundle",
                    ".photoslibrary", ".band", ".kext", ".plugin", ".xcodeproj", ".musiclibrary", ".tvlibrary",
                    ".patch", ".cst", ".pst")
APPLE_LIB_PATHS = ["/Library/Application Support/Logic", "/Library/Application Support/GarageBand",
                   "/Library/Audio/Apple Loops"]
# 決まった場所に置かれるメーカーのサウンド (探索範囲外なので個別に確認)
FIXED_LIB_PATHS = [("/Library/Arturia", "Arturia"), ("/Library/Audio/Sounds", ""), ("/Users/Shared/Toontrack", "Toontrack"),
                   ("/Library/Application Support/Spectrasonics/STEAM", "Spectrasonics (Omnisphere/Keyscape/Trilian)")]


def search_roots(include_volumes: bool) -> list[tuple[Path, int]]:
    roots = [
        (hp("Music"), 9), (hp("Documents"), 9), (hp("Desktop"), 7), (hp("Downloads"), 5),
        (hp("Dropbox"), 8), (hp("Library/Mobile Documents/com~apple~CloudDocs"), 8),
        (hp("Library/CloudStorage"), 9), (hp("Library/Application Support"), 4),
        (sp("/Users/Shared"), 7), (sp("/Library/Application Support"), 4), (hp("Movies"), 5),
    ]
    # ホーム直下のその他フォルダ (例: ~/Samples, ~/Kontakt Library など)
    std = {"music", "documents", "desktop", "downloads", "dropbox", "library", "movies", "pictures", "public",
           "applications", ".trash"}
    try:
        for d in hp().iterdir():
            if d.is_dir() and d.name.lower() not in std and not d.name.startswith("."):
                roots.append((d, 7))
    except OSError:
        pass
    if include_volumes:
        vol = sp("/Volumes")
        if vol.is_dir():
            for d in vol.iterdir():
                try:
                    if d.is_symlink():  # 起動ディスク (Macintosh HD) へのリンク
                        continue
                    if (d / "Backups.backupdb").exists() or d.name.lower().startswith(("time machine", "com.apple.timemachine")):
                        continue
                    if d.is_dir():
                        roots.append((d, 7))
                except OSError:
                    pass
    seen, out = set(), []
    for r, depth in roots:
        if r.is_dir() and str(r) not in seen:
            seen.add(str(r))
            out.append((r, depth))
    return out


def walk_everything(include_volumes: bool, time_budget: int) -> dict:
    projects, libraries, installers, sample_dirs = {}, {}, [], {}
    roots = search_roots(include_volumes)
    for root, maxdepth in roots:
        t0 = time.time()
        log("  探索中: {}".format(display_path(root)))
        base_depth = len(root.parts)
        timed_out = False
        for dp, dns, fns in os.walk(root, onerror=lambda e: None):
            if time.time() - t0 > time_budget:
                timed_out = True
                break
            here = Path(dp)
            depth = len(here.parts) - base_depth
            keep = []
            for d in dns:
                dl = d.lower()
                full = here / d
                if dl.endswith(PROJECT_EXTS):
                    projects[str(full)] = full
                    continue
                if dl.startswith(".") or dl in SKIP_DIR_NAMES or dl.endswith(PACKAGE_SUFFIXES):
                    continue
                if dl in KNOWN_LIB_DIRS and depth >= 0 and "downloads" not in str(here).lower():
                    libraries.setdefault(str(full), dict(path=full, vendor=KNOWN_LIB_DIRS[dl], kind="メーカー別フォルダ"))
                    continue
                if depth + 1 < maxdepth:
                    keep.append(d)
            dns[:] = keep
            lower = [f.lower() for f in fns]
            if any(f.endswith(LIB_MARKERS) for f in lower):
                libraries.setdefault(dp, dict(path=here, vendor="", kind="音源ライブラリ"))
                dns[:] = []
                continue
            n_samples = sum(1 for f in lower if f.endswith(SAMPLE_EXTS))
            if n_samples:
                sample_dirs[dp] = sample_dirs.get(dp, 0) + n_samples
            for f, fl in zip(fns, lower):
                if fl.endswith(INSTALLER_EXTS):
                    full = here / f
                    try:
                        st = full.stat()
                    except OSError:
                        continue
                    installers.append(dict(path=full, name=f, size=st.st_size, mtime=st.st_mtime))
        if timed_out:
            log("    ※ 時間上限 ({}秒) に達したので {} の探索を途中で打ち切りました".format(time_budget, display_path(root)))
    # サンプルファイルのあるフォルダを「ライブラリ」としてまとめる (既に見つけた場所の配下は除外)
    lib_paths = sorted(libraries.keys())
    for d in sorted(sample_dirs):
        if any(d == lp or d.startswith(lp.rstrip("/") + "/") for lp in lib_paths):
            continue
        p = Path(d)
        # 「Instruments」「Samples」など汎用名のフォルダなら1つ上をライブラリ名とみなす
        while p.name.lower() in ("instruments", "samples", "multis", "snapshots", "presets", "data", "content", "kontakt") and p.parent != p:
            p = p.parent
        key = str(p)
        if any(key == lp or key.startswith(lp.rstrip("/") + "/") for lp in lib_paths):
            continue
        libraries.setdefault(key, dict(path=p, vendor="", kind="サンプル音源フォルダ"))
        lib_paths.append(key)
        lib_paths.sort()
    for ap in APPLE_LIB_PATHS:
        p = sp(ap)
        if p.is_dir():
            libraries.setdefault(str(p), dict(path=p, vendor="Apple", kind="Logic 純正サウンドライブラリ"))
    for fp, vendor in FIXED_LIB_PATHS:
        p = sp(fp)
        if p.is_dir() and not any(str(p) == k or str(p).startswith(k.rstrip("/") + "/") for k in libraries):
            libraries.setdefault(str(p), dict(path=p, vendor=vendor, kind="メーカー別フォルダ"))
    return dict(projects=list(projects.values()), libraries=list(libraries.values()), installers=installers, roots=[display_path(r) for r, _ in roots])


def spotlight_projects() -> list[Path]:
    """Spotlight で .logicx を検索 (探索漏れの補完)"""
    if ROOT or not shutil.which("mdfind"):
        return []
    out = []
    for q in ('kMDItemFSName == "*.logicx"', 'kMDItemFSName == "*.logic"'):
        try:
            res = subprocess.run(["mdfind", q], capture_output=True, text=True, timeout=120)
            out += [Path(x) for x in res.stdout.splitlines() if x.strip()]
        except Exception:
            pass
    return [p for p in out if p.exists() and not any(x in str(p) for x in ("/.Trash", "Project File Backups", "Backups.backupdb"))]


# --------------------------------------------------------------------------------------
# 3. 音源ライブラリの詳細 (Native Instruments の登録情報 など)
# --------------------------------------------------------------------------------------
def native_instruments_registry() -> list[dict]:
    out = []
    for base in (sp("/Library/Preferences"), hp("Library/Preferences")):
        if not base.is_dir():
            continue
        for f in sorted(base.glob("com.native-instruments.*.plist")):
            pl = read_plist(f)
            if not isinstance(pl, dict):
                continue
            prod = f.name[len("com.native-instruments."):-len(".plist")]
            content = pl.get("ContentDir") or pl.get("ContentDirectory") or ""
            install = pl.get("InstallDir") or pl.get("InstallDirectory") or ""
            if not (content or install):
                continue
            exists = sp(content).exists() if content else None
            out.append(dict(product=prod, content_dir=content, install_dir=install,
                            version=str(pl.get("ContentVersion") or pl.get("Version") or ""),
                            content_exists=exists))
    return out


def enrich_libraries(libs: list[dict], measure: bool) -> list[dict]:
    out = []
    for i, L in enumerate(libs):
        p = L["path"]
        size = None
        if measure:
            size = dir_size(p, timeout=600)
        name = p.name
        # .nicnt にライブラリ正式名が入っていることがある
        try:
            nicnt = next((x for x in p.iterdir() if x.suffix.lower() == ".nicnt"), None)
        except OSError:
            nicnt = None
        if nicnt is not None:
            try:
                raw = nicnt.read_bytes()[:200000]
                m = re.search(rb"<Name>([^<]{2,120})</Name>", raw)
                if m:
                    name = m.group(1).decode("utf-8", "replace")
            except OSError:
                pass
        vendor = L.get("vendor") or guess_vendor(str(p))
        cat, desc, _ = classify(dict(vendor=vendor or "", name=name, bundle=p.name, au_full_name=""))
        dpth = display_path(p)
        vol = ("外付け: " + dpth.split("/")[2]) if dpth.startswith("/Volumes/") else "内蔵ディスク"
        out.append(dict(name=name, vendor=vendor, kind=L["kind"], path=display_path(p), size=size or 0,
                        location=vol, category=cat if cat not in ("other_fx",) else "other_inst"))
        if measure and (i + 1) % 10 == 0:
            log("    容量計算 {}/{}".format(i + 1, len(libs)))
    # 同名ライブラリが複数の場所にある → 重複の可能性
    by = {}
    for L in out:
        by.setdefault(norm(L["name"]), []).append(L)
    for k, ls in by.items():
        for L in ls:
            L["duplicate"] = len(ls) > 1 and len(k) > 3
    return out


def guess_vendor(text: str) -> str:
    t = text.lower()
    best = ""
    for v in KNOWN_VENDORS:
        if re.search(r"(^|[^a-z])" + re.escape(v) + r"([^a-z]|$)", t) and len(v) > len(best):
            best = v
    return pretty_vendor(best) if pretty_vendor(best) != best else best.title()


# --------------------------------------------------------------------------------------
# 4. 使用履歴 (Logic プロジェクトの中身を調べる)
# --------------------------------------------------------------------------------------
ASCII_RUN = re.compile(rb"[\x20-\x7e]{3,}")
UTF16_RUN = re.compile(rb"(?:[\x20-\x7e]\x00){3,}")


def extract_text(data: bytes) -> str:
    parts = [m.group(0).decode("ascii", "ignore") for m in ASCII_RUN.finditer(data)]
    parts += [m.group(0).decode("utf-16-le", "ignore") for m in UTF16_RUN.finditer(data)]
    return "\n".join(parts).lower()


def project_data_files(proj: Path) -> list[Path]:
    files = []
    if proj.suffix.lower() == ".logicx":
        alts = proj / "Alternatives"
        if alts.is_dir():
            for a in alts.iterdir():
                f = a / "ProjectData"
                if f.is_file():
                    files.append(f)
    else:
        for dp, dns, fns in os.walk(proj):
            dns[:] = [d for d in dns if "backup" not in d.lower()]
            for fn in fns:
                if fn in ("documentData", "ProjectData") or fn.lower().endswith(".lso"):
                    files.append(Path(dp) / fn)
    if not files and proj.is_file():
        files.append(proj)
    return files


def build_needles(products: list[dict]) -> list[tuple[dict, list[str], list[bytes]]]:
    out = []
    for p in products:
        names = set()
        for full in p["au_names"]:
            names.add(full.lower())
            if ":" in full:
                names.add(full.split(":", 1)[1].strip().lower())
        names.add(p["name"].lower())
        for v in p["variants"]:
            names.add(v.lower())
        good = []
        for n in names:
            n = n.strip()
            short = n.split(":", 1)[-1].strip()
            if len(short) < 4 or short in GENERIC_NAMES:
                if ":" in n and len(n) >= 8:
                    good.append(n)
                continue
            good.append(n)
        codes = []
        for _t, sub, man in p["codes"]:
            try:
                s = sub.encode("latin-1")
                m = man.encode("latin-1")
            except Exception:
                continue
            if len(s) == 4 and len(m) == 4:
                codes += [s + m, s[::-1] + m[::-1], m + s, m[::-1] + s[::-1]]
        out.append((p, sorted(set(good), key=len, reverse=True), codes))
    return out


def scan_usage(projects: list[Path], products: list[dict], libraries: list[dict]) -> list[dict]:
    needles = build_needles(products)
    lib_needles = [(L, L["name"].lower()) for L in libraries if len(L["name"]) >= 5 and L["name"].lower() not in GENERIC_NAMES]
    proj_rows = []
    for p in products:
        p.update(projects=[], last_used_ts=0, first_used_ts=0, match="")
    for L in libraries:
        L.update(projects=[], last_used_ts=0)
    for i, proj in enumerate(projects):
        files = project_data_files(proj)
        mt = 0.0
        texts, raws = [], []
        size = 0
        for f in files:
            try:
                st = f.stat()
                mt = max(mt, st.st_mtime)
                size += st.st_size
                if st.st_size > 400 * 1024 * 1024:
                    continue
                data = f.read_bytes()
            except OSError:
                continue
            raws.append(data)
            texts.append(extract_text(data))
        if not files:
            try:
                mt = proj.stat().st_mtime
            except OSError:
                pass
        text = "\n".join(texts)
        used = []
        for prod, names, codes in needles:
            how = ""
            if codes and any(c in raw for raw in raws for c in codes):
                how = "AUコード一致"
            else:
                for n in names:
                    if n in text:
                        how = "名前一致"
                        break
            if how:
                used.append(prod["name"])
                prod["projects"].append(dict(name=proj.name, path=display_path(proj), date=iso(mt)))
                prod["last_used_ts"] = max(prod["last_used_ts"], mt)
                prod["first_used_ts"] = min(prod["first_used_ts"] or mt, mt)
                if prod["match"] != "AUコード一致":
                    prod["match"] = how
        for L, n in lib_needles:
            if n in text:
                L["projects"].append(proj.name)
                L["last_used_ts"] = max(L["last_used_ts"], mt)
        proj_rows.append(dict(name=proj.name, path=display_path(proj), modified=iso(mt), modified_ts=mt,
                              alternatives=len(files), size=size, plugins=sorted(set(used))))
        if (i + 1) % 20 == 0 or i + 1 == len(projects):
            log("  プロジェクト解析 {}/{}".format(i + 1, len(projects)))
    return proj_rows


def scan_user_presets(products: list[dict]) -> None:
    """ユーザーが保存したプリセット (= 使ったことがある証拠) を探す"""
    dirs = []
    for base in (hp("Music/Audio Music Apps/Plug-In Settings"), hp("Library/Audio/Presets"), sp("/Library/Audio/Presets")):
        if base.is_dir():
            for dp, dns, fns in os.walk(base):
                depth = len(Path(dp).parts) - len(base.parts)
                if depth > 2:
                    dns[:] = []
                if fns or dns:
                    dirs.append(Path(dp).name.lower())
    names = set(dirs)
    patches_text = ""
    for base in (hp("Music/Audio Music Apps/Patches"), hp("Music/Audio Music Apps/Channel Strip Settings")):
        if base.is_dir():
            buf = []
            for dp, _dns, fns in os.walk(base):
                for fn in fns:
                    fp = Path(dp) / fn
                    try:
                        if fp.stat().st_size < 20 * 1024 * 1024:
                            buf.append(extract_text(fp.read_bytes()))
                    except OSError:
                        pass
            patches_text += "\n".join(buf)
    for p in products:
        nm = p["name"].lower()
        p["has_user_presets"] = nm in names or any(n.split(":", 1)[-1].strip() in names for n in [x.lower() for x in p["au_names"]])
        p["in_user_patches"] = len(nm) >= 4 and nm not in GENERIC_NAMES and nm in patches_text


# --------------------------------------------------------------------------------------
# 5. その他の環境情報
# --------------------------------------------------------------------------------------
MANAGER_APPS = ["Native Access", "Native Access 2", "Spitfire Audio", "iZotope Product Portal", "Waves Central",
                "Arturia Software Center", "Plugin Alliance Installation Manager", "UJAM App", "Toontrack Product Manager",
                "XLN Online Installer", "Installation Center", "EastWest Installation Center", "Splice", "Output Hub",
                "Slate Digital Connect", "UA Connect", "IK Product Manager", "Softube Central", "Kilohearts Installer",
                "Orchestral Tools", "Vienna Assistant", "Steinberg Download Assistant", "Celemony Melodyne",
                "Positive Grid Product Manager", "Neural DSP", "Heavyocity Portal", "Sonarworks", "Native Instruments",
                "Plugin Boutique Manager", "Best Service Engine", "UVI Portal", "Kontakt", "Kontakt 7", "Kontakt 8",
                "Komplete Kontrol", "Melodyne", "Synthesizer V Studio", "Logic Pro", "Logic Pro X", "MainStage",
                "GarageBand", "Ableton Live", "Pro Tools", "Cubase", "Studio One", "FL Studio", "Reaper", "Bitwig Studio"]


def scan_apps() -> list[dict]:
    out = []
    for base in (sp("/Applications"), hp("Applications")):
        if not base.is_dir():
            continue
        for dp, dns, _fns in os.walk(base):
            depth = len(Path(dp).parts) - len(base.parts)
            for d in list(dns):
                if d.endswith(".app"):
                    nm = d[:-4]
                    if any(nm.lower().startswith(a.lower()) for a in MANAGER_APPS):
                        info = read_plist(Path(dp) / d / "Contents" / "Info.plist") or {}
                        out.append(dict(name=nm, path=display_path(Path(dp) / d),
                                        version=str(info.get("CFBundleShortVersionString", ""))))
            dns[:] = [d for d in dns if not d.endswith(".app") and depth < 1]
    return out


def scan_logic_tags() -> dict:
    """Logic プラグインマネージャのカスタムカテゴリ (既存設定) を読む"""
    base = hp("Music/Audio Music Apps/Databases/Tags")
    out = dict(path=display_path(base), exists=base.is_dir(), files=0, categories={})
    if not base.is_dir():
        return out
    for f in base.iterdir():
        if not f.is_file():
            continue
        out["files"] += 1
        pl = read_plist(f)
        if isinstance(pl, dict):
            tags = pl.get("tags") or {}
            if isinstance(tags, dict):
                for t in tags:
                    out["categories"][t] = out["categories"].get(t, 0) + 1
    return out


def scan_receipts() -> list[str]:
    if ROOT or not shutil.which("pkgutil"):
        return []
    try:
        res = subprocess.run(["pkgutil", "--pkgs"], capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    keep = []
    for line in res.stdout.splitlines():
        l = line.lower()
        if l.startswith("com.apple."):
            continue
        if any(k.replace(" ", "") in l.replace("-", "").replace("_", "") for k in KNOWN_VENDORS if len(k) > 3) or any(
                x in l for x in ("audio", "plugin", "vst", "aax", "kontakt", "sound", "music")):
            keep.append(line)
    return keep


# --------------------------------------------------------------------------------------
# 6. 整理プランの生成
# --------------------------------------------------------------------------------------
AUDIO_HINT = re.compile(r"vst|\bau\b|aax|plug-?in|kontakt|library|sound|audio|synth|drum|guitar|bass|piano|vocal|"
                        r"orchestra|string|reverb|delay|comp|eq|mix|master|install|sample", re.I)


def classify_installers(installers: list[dict], products: list[dict]) -> list[dict]:
    prod_tokens = [(norm(p["name"]), p) for p in products if len(norm(p["name"])) >= 5]
    out = []
    for it in installers:
        name = it["name"]
        n = norm(name)
        vendor = guess_vendor(name)
        matched = next((p for t, p in prod_tokens if t in n), None)
        if matched and not vendor:
            vendor = matched["vendor"]
        audio = bool(vendor or matched or AUDIO_HINT.search(name))
        in_dl = "/downloads/" in str(it["path"]).lower()
        if not audio:
            continue
        out.append(dict(name=name, path=display_path(it["path"]), size=it["size"], date=iso(it["mtime"]),
                        vendor=vendor, product=matched["name"] if matched else "",
                        in_downloads=in_dl))
    return out


def sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def write_scripts(outdir: Path, products: list[dict], installers: list[dict], now_ts: float) -> None:
    dest_base = str(HOME / "Music" / "_プラグイン インストーラー保管庫")
    # --- インストーラー整理 ---
    lines = ["#!/bin/bash", "# 散らばったプラグインのインストーラーを メーカー別フォルダに集めます。",
             "# 移動先: " + dest_base, "# 元に戻したいときは undo_installers.sh を実行してください。",
             "# 同名ファイルがある場合は上書きしません (mv -n)。", "set -u", ""]
    undo = ["#!/bin/bash", "# organize_installers.sh で移動したファイルを元の場所に戻します。", "set -u", ""]
    for it in sorted(installers, key=lambda x: (x["vendor"], x["name"])):
        vendor = it["vendor"] or "メーカー不明"
        dst_dir = dest_base + "/" + vendor
        dst = dst_dir + "/" + it["name"]
        lines.append("mkdir -p {} && mv -n {} {}".format(sh_quote(dst_dir), sh_quote(it["path"]), sh_quote(dst)))
        undo.append("mv -n {} {}".format(sh_quote(dst), sh_quote(it["path"])))
    lines += ["", "echo '完了しました。Finder で開きます。'", "open {}".format(sh_quote(dest_base))]
    (outdir / "organize_installers.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (outdir / "undo_installers.sh").write_text("\n".join(undo) + "\n", encoding="utf-8")

    # --- 未使用 / Logic で不要なプラグインの退避 (すべてコメントアウト状態で生成) ---
    q = ["#!/bin/bash",
         "# ===============================================================",
         "#  使っていないプラグインを『退避フォルダ』に移すスクリプト (削除はしません)",
         "# ===============================================================",
         "#  ・最初はすべての行の先頭に # が付いていて、何も実行されません。",
         "#  ・退避したい行だけ先頭の # を消してから  bash quarantine_plugins.sh  で実行します。",
         "#  ・/Library 配下は管理者権限が必要なので、パスワードを聞かれます。",
         "#  ・退避先は Plug-Ins/_退避 です。Logic はここを読み込まないので、起動が軽くなります。",
         "#  ・戻すときは restore_plugins.sh の同じ行の # を外して実行します。",
         "#  ・Logic を終了してから実行してください。", ""]
    r = ["#!/bin/bash", "# quarantine_plugins.sh で退避したプラグインを元に戻します (戻したい行の # を外して実行)。", ""]

    # 1つのファイルに複数製品が入っている「シェル」(例: Waves の WaveShell) を把握する
    path_products: dict[str, list[dict]] = {}
    for p in products:
        for path in p["paths"]:
            path_products.setdefault(path, []).append(p)
    done_paths: set[str] = set()

    def add(section: str, items: list[tuple[dict, str]], allowed: tuple):
        picked = []
        for p, path in items:
            if path in done_paths:
                continue
            members = path_products.get(path, [p])
            if any(m["status"] not in allowed for m in members):
                continue  # シェル内に使用中の製品がある → 退避すると使えなくなるので対象外
            done_paths.add(path)
            picked.append((p if len(members) == 1 else dict(p, name="{} ほか{}製品を含むシェル".format(p["name"], len(members) - 1)), path))
        items = picked
        if not items:
            return
        q.append("")
        q.append("# ---- " + section + " ----")
        r.append("")
        r.append("# ---- " + section + " ----")
        for p, path in items:
            real = path
            parent, fname = real.rsplit("/", 1)
            qdir = re.sub(r"/Plug-Ins/", "/Plug-Ins/_退避/", parent, count=1) if "/Plug-Ins/" in parent else parent + "/_退避"
            sudo = "" if real.startswith(str(HOME)) else "sudo "
            q.append("# {}mkdir -p {} && {}mv -n {} {}   # {} [{}]".format(
                sudo, sh_quote(qdir), sudo, sh_quote(real), sh_quote(qdir + "/" + fname), p["name"], p.get("status_label", "")))
            r.append("# {}mv -n {} {}".format(sudo, sh_quote(qdir + "/" + fname), sh_quote(real)))

    never = [(p, path) for p in products if p["status"] == "unused" for path in p["paths"] if not path.endswith(".aaxplugin")]
    old = [(p, path) for p in products if p["status"] == "old" for path in p["paths"] if not path.endswith(".aaxplugin")]
    aax = [(p, path) for p in products for path in p["paths"] if path.endswith(".aaxplugin")]
    add("一度も使われていないプラグイン (Logic プロジェクト内に見つからず)", never, ("unused",))
    add("1年以上使っていないプラグイン", old, ("unused", "old"))
    add("AAX 形式 (Pro Tools 専用。Logic では使えません。Pro Tools を使わないなら不要)", aax,
        ("used", "old", "unused", "preset_only", "not_logic"))
    (outdir / "quarantine_plugins.sh").write_text("\n".join(q) + "\n", encoding="utf-8")
    (outdir / "restore_plugins.sh").write_text("\n".join(r) + "\n", encoding="utf-8")
    for f in ("organize_installers.sh", "undo_installers.sh", "quarantine_plugins.sh", "restore_plugins.sh"):
        try:
            os.chmod(outdir / f, 0o755)
        except OSError:
            pass


def write_logic_category_guide(outdir: Path, products: list[dict]) -> None:
    lines = ["# Logic Pro プラグインマネージャ用 カテゴリ分け表", "",
             "Logic の **プラグイン・マネージャ**（メニュー: Logic Pro → プラグイン・マネージャ）で、",
             "左下の「+」から下のカテゴリ（フォルダ）を作り、各プラグインをドラッグして入れてください。",
             "すると、トラックにプラグインを挿すときのメニューがこのフォルダ別に整理されます。", "",
             "> 💡 実ファイルを動かす必要はありません。プラグイン本体は決まった場所にないと Logic が読み込めないため、",
             "> 「見た目の整理」はプラグインマネージャで行うのが安全で正しい方法です。", ""]
    by: dict[str, list[dict]] = {}
    for p in products:
        if not p["logic_usable"]:
            continue
        by.setdefault(p["category"], []).append(p)
    for key, label, logic_name in CATEGORIES:
        items = by.get(key)
        if not items:
            continue
        lines.append("## 📁 {}  （{}）".format(logic_name, len(items)))
        lines.append("")
        lines.append("| プラグイン | メーカー | 種類 | 使用状況 |")
        lines.append("|---|---|---|---|")
        for p in sorted(items, key=lambda x: (x["vendor"].lower(), x["name"].lower())):
            lines.append("| {} | {} | {} | {} |".format(p["name"], p["vendor"], p["kind"], p["status_label"]))
        lines.append("")
    unused = [p for p in products if p["logic_usable"] and p["status"] == "unused"]
    if unused:
        lines += ["## 📁 00 未使用・お試し中  （{}）".format(len(unused)), "",
                  "上の分類とは別に、まだ使っていないものだけを集めたフォルダを作っておくと「買ったのに使ってない」を把握しやすくなります。",
                  "", ", ".join(sorted(p["name"] for p in unused)), ""]
    (outdir / "logic_categories.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# 7. レポート出力
# --------------------------------------------------------------------------------------
def status_of(p: dict, now_ts: float) -> tuple[str, str]:
    if p["last_used_ts"]:
        days = (now_ts - p["last_used_ts"]) / 86400
        if days <= 365:
            return "used", "使用中（1年以内）"
        return "old", "過去に使用（1年以上前）"
    if p.get("has_user_presets") or p.get("in_user_patches"):
        return "preset_only", "プリセット保存あり（プロジェクトでは未確認）"
    if not p["logic_usable"]:
        return "not_logic", "Logicでは使えない形式のみ"
    return "unused", "未使用"


def _write_csv_raw(path: Path, rows: list[dict], cols: list[tuple[str, str]]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel / Numbers で文字化けしない
        w = csv.writer(f)
        w.writerow([h for _k, h in cols])
        for r in rows:
            w.writerow([r.get(k, "") if not isinstance(r.get(k), (list, set, tuple)) else " / ".join(map(str, r.get(k))) for k, _h in cols])


def build_report(outdir: Path, data: dict) -> Path:
    html_path = outdir / "report.html"
    payload = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    html_path.write_text(HTML_TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    return html_path


HTML_TEMPLATE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Logic プラグイン総点検</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--sub:#6e6e73;--line:#e3e1dc;--acc:#2f6fed;--ok:#1f9d55;--warn:#c27c0e;--bad:#c2410c;--muted:#8a8a8f;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1e1e21;--ink:#f2f2f4;--sub:#a1a1a6;--line:#2e2e33;--acc:#6b9bff;--ok:#4ade80;--warn:#fbbf24;--bad:#fb923c;--muted:#8a8a8f;--chip:#2a2a2e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"Hiragino Sans","Hiragino Kaku Gothic ProN",sans-serif}
header{padding:28px 24px 8px;max-width:1280px;margin:auto}h1{font-size:24px;margin:0 0 4px}header p{color:var(--sub);margin:0}
nav{position:sticky;top:0;background:var(--bg);z-index:5;border-bottom:1px solid var(--line)}nav div{max-width:1280px;margin:auto;padding:0 16px;display:flex;gap:4px;overflow-x:auto}
nav button{border:0;background:none;color:var(--sub);padding:12px 12px;font:inherit;cursor:pointer;white-space:nowrap;border-bottom:2px solid transparent}
nav button.on{color:var(--ink);border-bottom-color:var(--acc);font-weight:600}
main{max-width:1280px;margin:auto;padding:16px}section{display:none}section.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}.card b{display:block;font-size:26px;font-variant-numeric:tabular-nums}.card span{color:var(--sub);font-size:12px}
h2{font-size:17px;margin:24px 0 10px}.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--sub);font-weight:600;position:sticky;top:0;background:var(--card);cursor:pointer}
.tw{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:auto;max-height:75vh}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;background:var(--chip);font-size:12px;margin:1px 2px 1px 0;white-space:nowrap}
.s-used{color:var(--ok)}.s-old{color:var(--warn)}.s-unused{color:var(--bad)}.s-preset_only{color:var(--acc)}.s-not_logic{color:var(--muted)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}input,select{font:inherit;padding:7px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink)}input{flex:1;min-width:180px}
.bar{display:flex;height:10px;border-radius:99px;overflow:hidden;background:var(--chip);min-width:120px}.bar i{display:block;height:100%}
.small{color:var(--sub);font-size:12px}.path{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--sub);word-break:break-all}
code{font-family:ui-monospace,Menlo,monospace;background:var(--chip);padding:1px 6px;border-radius:5px}
.catgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}.catgrid .box{margin:0}.catgrid h3{margin:0 0 6px;font-size:15px}
ol li{margin-bottom:6px}
</style></head><body>
<header><h1>🎛️ Logic Pro プラグイン総点検レポート</h1><p id="meta"></p></header>
<nav><div id="tabs"></div></nav><main id="main"></main>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const hs=n=>{if(!n)return"-";const u=["B","KB","MB","GB","TB"];let i=0;while(n>=1024&&i<4){n/=1024;i++}return(i<2?n.toFixed(0):n.toFixed(1))+" "+u[i]};
const CL=Object.fromEntries(D.categories.map(c=>[c[0],c[1]]));
const SL={used:"使用中（1年以内）",old:"過去に使用（1年以上前）",unused:"未使用",preset_only:"プリセットのみ",not_logic:"Logic非対応形式のみ"};
const SC={used:"var(--ok)",old:"var(--warn)",unused:"var(--bad)",preset_only:"var(--acc)",not_logic:"var(--muted)"};
$("#meta").textContent=`作成日時 ${D.generated} ・ プロジェクト ${D.projects.length} 件を解析 ・ 所要 ${D.elapsed}`;
const P=D.products;const tabs=[["sum","サマリー"],["cat","役割別"],["all","プラグイン一覧"],["unused","未使用"],["lib","音源ライブラリ"],["inst","インストーラー"],["proj","プロジェクト"],["plan","整理プラン"],["issue","要注意"]];
$("#tabs").innerHTML=tabs.map((t,i)=>`<button data-t="${t[0]}" class="${i?"":"on"}">${t[1]}</button>`).join("");
$("#main").innerHTML=tabs.map((t,i)=>`<section id="t-${t[0]}" class="${i?"":"on"}"></section>`).join("");
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>{document.querySelectorAll("nav button,section").forEach(x=>x.classList.remove("on"));b.classList.add("on");$("#t-"+b.dataset.t).classList.add("on")});
const cnt=(a,f)=>a.filter(f).length;const st=k=>cnt(P,p=>p.status===k);
const logicP=P.filter(p=>p.logic_usable);
// summary
{const u=st("used"),o=st("old"),n=st("unused"),pr=st("preset_only");const tot=logicP.length;
const libSize=D.libraries.reduce((a,b)=>a+(b.size||0),0),instSize=D.installers.reduce((a,b)=>a+(b.size||0),0);
const unusedSize=P.filter(p=>p.status==="unused").reduce((a,b)=>a+(b.size||0),0);
let h=`<div class="cards">
<div class="card"><span>Logicで使えるプラグイン（製品数）</span><b>${tot}</b><span>ファイル総数 ${D.plugin_files}</span></div>
<div class="card"><span>使用中（直近1年）</span><b style="color:var(--ok)">${u}</b><span>${tot?Math.round(u/tot*100):0}%</span></div>
<div class="card"><span>過去に使用（1年以上前）</span><b style="color:var(--warn)">${o}</b><span>${tot?Math.round(o/tot*100):0}%</span></div>
<div class="card"><span>一度も使っていない</span><b style="color:var(--bad)">${n}</b><span>${tot?Math.round(n/tot*100):0}%（+プリセットのみ ${pr}）</span></div>
<div class="card"><span>音源ライブラリ</span><b>${D.libraries.length}</b><span>合計 ${hs(libSize)}</span></div>
<div class="card"><span>散らばったインストーラー</span><b>${D.installers.length}</b><span>合計 ${hs(instSize)}</span></div></div>`;
h+=`<div class="box"><b>使用状況の内訳</b><div class="bar" style="margin-top:8px;height:14px">${["used","old","preset_only","unused"].map(k=>`<i style="width:${tot?st(k)/tot*100:0}%;background:${SC[k]}" title="${SL[k]}"></i>`).join("")}</div>
<p class="small">判定方法：Logic プロジェクト（.logicx）の中身を全部読み、各プラグインの名前・AUコードが含まれているかで判定しています。「未使用」でも MainStage や他のDAW、テンプレート外で使った可能性はあります。</p></div>`;
h+=`<h2>役割別の数と使用率</h2><div class="tw"><table><tr><th>役割</th><th>数</th><th>使用中</th><th>過去</th><th>未使用</th><th style="width:30%">内訳</th></tr>`+
D.categories.map(c=>{const a=logicP.filter(p=>p.category===c[0]);if(!a.length)return"";const f=k=>cnt(a,p=>p.status===k);
return`<tr><td>${esc(c[1])}</td><td>${a.length}</td><td class="s-used">${f("used")}</td><td class="s-old">${f("old")}</td><td class="s-unused">${f("unused")}</td><td><div class="bar">${["used","old","preset_only","unused"].map(k=>`<i style="width:${f(k)/a.length*100}%;background:${SC[k]}"></i>`).join("")}</div></td></tr>`}).join("")+`</table></div>`;
const top=[...P].filter(p=>p.projects.length).sort((a,b)=>b.projects.length-a.projects.length).slice(0,15);
h+=`<h2>よく使っているプラグイン TOP15</h2><div class="tw"><table><tr><th>プラグイン</th><th>役割</th><th>使用プロジェクト数</th><th>最終使用</th></tr>${top.map(p=>`<tr><td><b>${esc(p.name)}</b> <span class="small">${esc(p.vendor)}</span></td><td>${esc(CL[p.category])}</td><td>${p.projects.length}</td><td>${p.last_used}</td></tr>`).join("")}</table></div>`;
h+=`<h2>使っていない容量</h2><div class="box">未使用プラグイン本体の合計：<b>${hs(unusedSize)}</b>（音源ライブラリの容量は「音源ライブラリ」タブ参照）</div>`;
$("#t-sum").innerHTML=h;}
// by category
{let h=`<p class="small">各プラグインが「何をするものか」を役割別にまとめました。分類は名前からの自動判定なので、違っていたら <code>category_overrides.csv</code> を直して再実行すると反映されます。</p><div class="catgrid">`;
for(const c of D.categories){const a=P.filter(p=>p.category===c[0]);if(!a.length)continue;
h+=`<div class="box"><h3>${esc(c[1])} <span class="small">${a.length}</span></h3><div class="small" style="margin-bottom:6px">Logicでのフォルダ名：<code>${esc(c[2])}</code></div>`+a.sort((x,y)=>(y.projects.length-x.projects.length)||x.name.localeCompare(y.name)).map(p=>`<div style="margin:6px 0"><b>${esc(p.name)}</b> <span class="small">${esc(p.vendor)}</span> <span class="chip s-${p.status}">${SL[p.status]}</span><div class="small">${esc(p.desc)}</div></div>`).join("")+`</div>`}
$("#t-cat").innerHTML=h+`</div>`;}
// table helper
function table(el,rows,cols,opts={}){let sortK=null,dir=1;const sec=$(el);
const fl=opts.filters?`<div class="filters"><input placeholder="検索（名前・メーカー・パス）" class="q">${opts.filters.map(f=>`<select data-k="${f[0]}"><option value="">${f[1]}：すべて</option>${f[2].map(o=>`<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("")}</select>`).join("")}<span class="small n"></span></div>`:"";
sec.innerHTML=(opts.intro||"")+fl+`<div class="tw"><table><thead><tr>${cols.map((c,i)=>`<th data-i="${i}">${c[0]}</th>`).join("")}</tr></thead><tbody></tbody></table></div>`;
const draw=()=>{let r=rows;const q=sec.querySelector(".q");if(q&&q.value){const s=q.value.toLowerCase();r=r.filter(x=>JSON.stringify(x).toLowerCase().includes(s))}
sec.querySelectorAll("select").forEach(s=>{if(s.value)r=r.filter(x=>String(x[s.dataset.k]).includes(s.value))});
if(sortK!==null){const k=cols[sortK][2]||(x=>x[cols[sortK][1]]);r=[...r].sort((a,b)=>{const A=k(a),B=k(b);return(A>B?1:A<B?-1:0)*dir})}
const n=sec.querySelector(".n");if(n)n.textContent=r.length+" 件";
sec.querySelector("tbody").innerHTML=r.map(x=>`<tr>${cols.map(c=>`<td>${c[3]?c[3](x):esc(x[c[1]])}</td>`).join("")}</tr>`).join("")};
sec.querySelectorAll("input,select").forEach(e=>e.oninput=draw);sec.querySelectorAll("th").forEach(th=>th.onclick=()=>{const i=+th.dataset.i;dir=sortK===i?-dir:1;sortK=i;draw()});draw()}
const catOpts=D.categories.map(c=>[c[0],c[1]]);const stOpts=Object.entries(SL);
const pcols=[["プラグイン","name",x=>x.name.toLowerCase(),x=>`<b>${esc(x.name)}</b><div class="small">${esc(x.desc)}</div>`],["メーカー","vendor"],["役割","category",x=>x.category,x=>esc(CL[x.category])],["種類","kind"],
["使用状況","status",x=>x.status,x=>`<span class="s-${x.status}">${SL[x.status]}</span>`],["使用数","n",x=>x.projects.length,x=>x.projects.length||""],["最終使用","last_used"],["形式","formats",x=>x.formats.join(),x=>x.formats.map(f=>`<span class="chip">${f}</span>`).join("")],
["対応CPU","arch"],["バージョン","versions",x=>x.versions.join(),x=>esc(x.versions.join(", "))],["インストール日","installed"],["サイズ","size",x=>x.size,x=>hs(x.size)],["場所","paths",x=>x.paths.join(),x=>x.paths.map(p=>`<div class="path">${esc(p)}</div>`).join("")]];
table("#t-all",P,pcols,{filters:[["category","役割",catOpts],["status","使用状況",stOpts]]});
table("#t-unused",P.filter(p=>p.status==="unused"||p.status==="preset_only"),pcols,{intro:`<p class="small">Logic プロジェクトの中で一度も見つからなかったプラグインです。気になるものから試してみるか、不要なら「整理プラン」の退避スクリプトで外せます（削除ではなく移動なので戻せます）。</p>`,filters:[["category","役割",catOpts]]});
table("#t-lib",D.libraries,[["ライブラリ","name",null,x=>`<b>${esc(x.name)}</b>${x.duplicate?' <span class="chip s-old">重複の可能性</span>':""}`],["メーカー","vendor"],["種別","kind"],["役割","category",null,x=>esc(CL[x.category]||"")],["容量","size",x=>x.size,x=>hs(x.size)],["置き場所","location"],["使用プロジェクト","p",x=>x.projects.length,x=>x.projects.length||""],["パス","path",null,x=>`<div class="path">${esc(x.path)}</div>`]],
{intro:`<p class="small">Kontakt 等のサンプル音源の保存場所です。容量が大きいので、外付けSSDにまとめるとMac本体の容量が空きます（移動後は各メーカーのアプリで場所を指定し直す必要があります）。</p>`,filters:[]});
table("#t-inst",D.installers,[["ファイル","name",null,x=>`<b>${esc(x.name)}</b>`],["メーカー推定","vendor"],["対応する製品","product"],["容量","size",x=>x.size,x=>hs(x.size)],["日付","date"],["場所","path",null,x=>`<div class="path">${esc(x.path)}</div>`]],
{intro:`<p class="small">ダウンロード等に散らばっているプラグイン関連のインストーラーです。<code>organize_installers.sh</code> で「ミュージック/_プラグイン インストーラー保管庫/メーカー名」にまとめられます。インストール済みのものは基本的に削除してもOK（メーカーのサイトから再ダウンロード可能）。</p>`,filters:[]});
table("#t-proj",D.projects,[["プロジェクト","name",null,x=>`<b>${esc(x.name)}</b>`],["更新日","modified"],["使用プラグイン数","n",x=>x.plugins.length,x=>x.plugins.length],["使用プラグイン","plugins",null,x=>x.plugins.map(p=>`<span class="chip">${esc(p)}</span>`).join("")],["場所","path",null,x=>`<div class="path">${esc(x.path)}</div>`]],{filters:[]});
// plan
$("#t-plan").innerHTML=`<div class="box"><h2 style="margin-top:0">おすすめの整理手順</h2><ol>
<li><b>Logic の中の見た目を整理（いちばん効果大・安全）</b><br>Logic Pro → <b>プラグイン・マネージャ</b> を開き、左下の「＋」で <code>logic_categories.md</code> にあるカテゴリ（01 ドラム・パーカッション 〜 20 MIDI・作曲支援）を作って、プラグインをドラッグします。トラックにプラグインを挿すメニューが役割別になります。</li>
<li><b>散らばったインストーラーを1か所に集める</b><br>ターミナルで <code>bash organize_installers.sh</code>。元に戻すときは <code>bash undo_installers.sh</code>。</li>
<li><b>使っていない／Logicで使えない形式を退避（任意）</b><br><code>quarantine_plugins.sh</code> をテキストエディタで開き、退避したい行の先頭の <code>#</code> を消して実行。削除ではなく移動なので <code>restore_plugins.sh</code> で戻せます。</li>
<li><b>音源ライブラリを外付けSSDにまとめる（任意・容量が足りない場合）</b><br>Native Access / Spitfire Audio アプリ / Spectrasonics / Toontrack 等の各アプリの「場所の変更（Relocate）」機能で移動します。Finder で直接動かすと音源が鳴らなくなるので注意。</li>
<li><b>分類の手直し</b><br><code>category_overrides.csv</code> の「カテゴリ」列を書き換えて <code>python3 plugin_audit.py --overrides category_overrides.csv</code> で再実行。</li></ol></div>
<div class="box"><h2 style="margin-top:0">プラグイン本体のファイルを動かしてはいけない理由</h2><p>AU プラグインは <code>/Library/Audio/Plug-Ins/Components</code> などの決まった場所に置かれていないと Logic が読み込めません。このため「フォルダ整理」は実ファイルではなく、プラグイン・マネージャのカテゴリで行います。</p></div>
<div class="box"><h2 style="margin-top:0">プラグインの置き場所（このMacで見つかったもの）</h2>${[...new Set(P.flatMap(p=>p.paths.map(x=>x.replace(/\/[^/]+$/,""))))].sort().map(d=>`<div class="path">${esc(d)}</div>`).join("")}</div>
<div class="box"><h2 style="margin-top:0">インストール管理アプリ</h2>${D.apps.map(a=>`<span class="chip">${esc(a.name)} ${esc(a.version)}</span>`).join("")||"見つかりませんでした"}</div>`;
// issues
{const intel=P.filter(p=>p.intel_only&&p.logic_usable),aax=P.filter(p=>p.formats.includes("AAX")),onlyNon=P.filter(p=>!p.logic_usable&&p.formats.some(f=>f!=="AAX")),dup=D.libraries.filter(l=>l.duplicate);
const ni=D.ni_registry.filter(x=>x.content_exists===false);
const L=(t,a,f)=>`<div class="box"><h2 style="margin-top:0">${t} <span class="small">${a.length}</span></h2>${a.length?a.map(f).join(""):'<span class="small">該当なし 👍</span>'}</div>`;
$("#t-issue").innerHTML=L("Intel専用（Apple Silicon Mac では Rosetta 起動が必要・動作が重い）",intel,p=>`<div>${esc(p.name)} <span class="small">${esc(p.vendor)} / ${esc(p.arch)}</span></div>`)+
L("AU版がない（Logic では使えない。VST/VST3/CLAP のみ）",onlyNon,p=>`<div>${esc(p.name)} <span class="small">${esc(p.formats.join(", "))}</span></div>`)+
L("AAX 形式（Pro Tools 専用。Pro Tools を使わないなら不要）",aax,p=>`<div>${esc(p.name)}</div>`)+
L("同じ名前の音源ライブラリが複数の場所にある（重複の可能性）",dup,l=>`<div>${esc(l.name)} <span class="path">${esc(l.path)}</span> ${hs(l.size)}</div>`)+
L("Native Instruments：登録されているのにフォルダが見つからない音源",ni,x=>`<div>${esc(x.product)} <span class="path">${esc(x.content_dir)}</span></div>`);}
</script></body></html>
"""


# --------------------------------------------------------------------------------------
# メイン
# --------------------------------------------------------------------------------------
def load_overrides(path: str) -> dict:
    out = {}
    if not path:
        return out
    label_to_key = {l: k for k, l, _ in CATEGORIES}
    label_to_key.update({g: k for k, _, g in CATEGORIES})
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            k = (row.get("キー") or "").strip()
            cat = (row.get("カテゴリ") or "").strip()
            cat = label_to_key.get(cat, cat)
            if k and cat in CAT_LABEL:
                out[k] = cat
    return out


def main() -> int:
    global ROOT, HOME, START
    ap = argparse.ArgumentParser(description="Logic Pro プラグイン総点検ツール")
    ap.add_argument("--quick", action="store_true", help="外付けドライブを探さず、ライブラリ容量の計算も省略 (速い)")
    ap.add_argument("--no-volumes", action="store_true", help="外付けドライブ (/Volumes) を探さない")
    ap.add_argument("--no-sizes", action="store_true", help="音源ライブラリの容量計算を省略")
    ap.add_argument("--time-budget", type=int, default=900, help="1つの探索場所にかける最大秒数 (既定 900)")
    ap.add_argument("--out", default="", help="出力先フォルダ (既定: デスクトップ/Logicプラグイン点検_日時)")
    ap.add_argument("--overrides", default="", help="カテゴリを手直しした category_overrides.csv")
    ap.add_argument("--extra-projects", nargs="*", default=[], help="追加で探すプロジェクトフォルダ")
    ap.add_argument("--root", default="", help=argparse.SUPPRESS)  # テスト用
    ap.add_argument("--home", default="", help=argparse.SUPPRESS)  # テスト用
    ap.add_argument("--no-open", action="store_true", help="終了後にレポートを自動で開かない")
    args = ap.parse_args()
    ROOT = args.root.rstrip("/")
    if args.home:
        HOME = Path(args.home)
    START = time.time()
    now_ts = time.time()

    print("=" * 64)
    print(" Logic Pro プラグイン総点検ツール v{}".format(VERSION))
    print(" ※ このツールは読み取りのみ。ファイルの移動・削除は一切しません。")
    print("=" * 64)

    log("① インストール済みプラグインを調べています…")
    rows = scan_plugins()
    products = group_products(rows)
    overrides = load_overrides(args.overrides)
    for p in products:
        if p["key"] in overrides:
            p["category"] = overrides[p["key"]]
            p["category_reason"] = "手動指定"
            if p["desc"] in CAT_DEFAULT_DESC.values():
                p["desc"] = CAT_DEFAULT_DESC[p["category"]]
    log("   → プラグインファイル {} 個 / 製品 {} 種類".format(len(rows), len(products)))

    log("② プロジェクト・音源ライブラリ・インストーラーを探しています（ここが一番時間がかかります）…")
    found = walk_everything(include_volumes=not (args.quick or args.no_volumes), time_budget=args.time_budget)
    projects = {str(p): p for p in found["projects"]}
    for p in spotlight_projects():
        projects.setdefault(str(p), p)
    for extra in args.extra_projects:
        for dp, dns, _f in os.walk(extra):
            for d in list(dns):
                if d.lower().endswith(PROJECT_EXTS):
                    projects.setdefault(str(Path(dp) / d), Path(dp) / d)
                    dns.remove(d)
    proj_list = sorted(projects.values(), key=lambda p: str(p))
    log("   → Logic プロジェクト {} 個 / 音源ライブラリ候補 {} 個 / インストーラー候補 {} 個".format(
        len(proj_list), len(found["libraries"]), len(found["installers"])))

    log("③ 音源ライブラリの情報を集めています…")
    libraries = enrich_libraries(found["libraries"], measure=not (args.quick or args.no_sizes))
    ni = native_instruments_registry()

    log("④ 過去のプロジェクトを1つずつ読んで、使ったプラグインを調べています…")
    proj_rows = scan_usage(proj_list, products, libraries)
    scan_user_presets(products)
    for p in products:
        p["status"], p["status_label"] = status_of(p, now_ts)
        p["last_used"] = iso(p["last_used_ts"])
        p["first_used"] = iso(p["first_used_ts"])
        p["projects"].sort(key=lambda x: x["date"], reverse=True)
    for L in libraries:
        L["last_used"] = iso(L.get("last_used_ts"))

    log("⑤ そのほかの情報（管理アプリ・Logic のカテゴリ設定 など）…")
    apps = scan_apps()
    tags = scan_logic_tags()
    receipts = scan_receipts()
    installers = classify_installers(found["installers"], products)

    # ---------------- 出力 ----------------
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    outdir = Path(args.out) if args.out else (HOME / "Desktop" / ("Logicプラグイン点検_" + stamp))
    if not args.out and not (HOME / "Desktop").is_dir():
        outdir = Path.cwd() / ("Logicプラグイン点検_" + stamp)
    outdir.mkdir(parents=True, exist_ok=True)
    log("⑥ レポートを書き出しています → {}".format(outdir))

    products.sort(key=lambda p: (CAT_ORDER.get(p["category"], 99), p["vendor"].lower(), p["name"].lower()))
    for p in products:
        for k in ("au_names", "variants"):
            p[k] = sorted(p[k])
        p["codes"] = ["/".join(c) for c in sorted(p["codes"])]

    write_csv(outdir / "plugins.csv", products, [
        ("name", "プラグイン"), ("vendor", "メーカー"), ("category_label", "役割"), ("desc", "機能"), ("kind", "種類"),
        ("status_label", "使用状況"), ("n_projects", "使用プロジェクト数"), ("last_used", "最終使用日"),
        ("first_used", "初使用日"), ("formats", "形式"), ("arch", "対応CPU"), ("versions", "バージョン"),
        ("installed", "インストール日"), ("size_h", "サイズ"), ("paths", "場所")])
    write_csv(outdir / "libraries.csv", libraries, [
        ("name", "ライブラリ"), ("vendor", "メーカー"), ("kind", "種別"), ("size_h", "容量"), ("location", "置き場所"),
        ("path", "パス"), ("duplicate", "重複の可能性"), ("last_used", "最終使用(推定)")])
    write_csv(outdir / "installers.csv", installers, [
        ("name", "ファイル"), ("vendor", "メーカー推定"), ("product", "対応製品"), ("size_h", "容量"),
        ("date", "日付"), ("path", "場所")])
    write_csv(outdir / "projects.csv", proj_rows, [
        ("name", "プロジェクト"), ("modified", "更新日"), ("plugins", "使用プラグイン"), ("path", "場所")])
    with open(outdir / "category_overrides.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["キー", "プラグイン", "メーカー", "カテゴリ", "判定根拠", "（選べるカテゴリ）"])
        choices = " / ".join(l for _k, l, _g in CATEGORIES)
        for i, p in enumerate(products):
            w.writerow([p["key"], p["name"], p["vendor"], CAT_LABEL[p["category"]], p["category_reason"], choices if i == 0 else ""])
    write_scripts(outdir, products, installers, now_ts)
    write_logic_category_guide(outdir, products)

    elapsed = time.time() - START
    data = dict(
        version=VERSION, generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        elapsed="{}分{}秒".format(int(elapsed // 60), int(elapsed % 60)),
        categories=CATEGORIES, products=products, plugin_files=len(rows), plugin_file_rows=rows,
        libraries=libraries, installers=installers, projects=proj_rows, apps=apps, logic_tags=tags,
        ni_registry=ni, receipts=receipts, search_roots=found["roots"],
    )
    for p in products:
        p.pop("installed_ts", None)
    (outdir / "audit.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    report = build_report(outdir, data)

    lu = [p for p in products if p["logic_usable"]]
    c = lambda s: sum(1 for p in lu if p["status"] == s)
    summary = [
        "# Logic Pro プラグイン総点検 サマリー ({})".format(data["generated"]), "",
        "| 項目 | 数 |", "|---|---|",
        "| Logic で使えるプラグイン（製品） | {} |".format(len(lu)),
        "| 使用中（直近1年） | {} |".format(c("used")),
        "| 過去に使用（1年以上前） | {} |".format(c("old")),
        "| プリセット保存のみ | {} |".format(c("preset_only")),
        "| 一度も使っていない | {} |".format(c("unused")),
        "| 解析した Logic プロジェクト | {} |".format(len(proj_rows)),
        "| 音源ライブラリ | {}（合計 {}） |".format(len(libraries), human_size(sum(L["size"] for L in libraries))),
        "| 散らばったインストーラー | {}（合計 {}） |".format(len(installers), human_size(sum(i["size"] for i in installers))),
        "", "## 役割別", "", "| 役割 | 数 | 使用中 | 過去 | 未使用 |", "|---|---|---|---|---|",
    ]
    for k, label, _g in CATEGORIES:
        a = [p for p in lu if p["category"] == k]
        if a:
            summary.append("| {} | {} | {} | {} | {} |".format(label, len(a), sum(p["status"] == "used" for p in a),
                                                            sum(p["status"] == "old" for p in a), sum(p["status"] == "unused" for p in a)))
    (outdir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print()
    print("\n".join(summary[:13]))
    print()
    log("完了！ レポート: {}".format(report))
    print("  ・report.html ……… ブラウザで見るメインのレポート")
    print("  ・logic_categories.md … Logic のプラグインマネージャ用カテゴリ分け表")
    print("  ・organize_installers.sh / quarantine_plugins.sh … 整理用スクリプト（中身を確認してから実行）")
    print("  ・audit.json …………… 全データ（Claude に渡すとさらに詳しく分析できます）")
    if not args.no_open and not ROOT and sys.platform == "darwin":
        subprocess.run(["open", str(report)])
    return 0


def write_csv(path: Path, rows: list[dict], cols: list[tuple[str, str]]) -> None:
    """表示用の派生列 (役割名・件数・容量表記) を足してから CSV に書く"""
    for r in rows:
        if "category" in r:
            r.setdefault("category_label", CAT_LABEL.get(r["category"], r["category"]))
        if "projects" in r and isinstance(r["projects"], list):
            r["n_projects"] = len(r["projects"])
        if "size" in r:
            r["size_h"] = human_size(r["size"])
        if "duplicate" in r:
            r["duplicate"] = "はい" if r["duplicate"] is True else ("" if r["duplicate"] is False else r["duplicate"])
    _write_csv_raw(path, rows, cols)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n中断しました。")
        sys.exit(130)

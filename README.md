# セミナー・コンテンツの告知文をつくるスキル

セミナー、講座、教材、有料コンテンツの告知文を、読者が参加・購入を判断できる形に整えます。Claude CodeとCodexで使うための`SKILL.md`形式です。

読者の困りごと、参加後の使い方、初心者が進める理由、実践内容、費用・条件の伝え方を整理したスキルです。売上や成果の保証を足したり、存在しない特典・締切を作ったりすることはありません。構成の考え方は[patterns.md](skills/announcement-copy/references/patterns.md)に記載しています。

## できること

- 元の条件を保ちながら、告知文の冒頭・体験内容・申込案内を改善する。
- 告知ページ、短いSNS投稿、メールなど、指定媒体に合わせて書く。
- 既存の資料から情報を拾い、未確定の日時や料金を勝手に埋めずに進める。
- 画像が必要なら、構図・文字・サイズ・費用を確認してから生成する。

本文作成にはAPIキーは不要です。文章は利用中のClaude CodeやCodexが作成します。画像APIの利用は任意です。

## Claude Codeで使う

リポジトリを取得し、スキルのフォルダを配置します。

```bash
git clone https://github.com/kochan630/announcement-copy-skill.git
cd announcement-copy-skill
mkdir -p ~/.claude/skills
if [ -e ~/.claude/skills/announcement-copy ]; then
  echo '同名のスキルがあります。内容を確認してから更新してください。'
else
  cp -R skills/announcement-copy ~/.claude/skills/announcement-copy
fi
```

特定のプロジェクトだけで使う場合は、そのプロジェクトの`.claude/skills/announcement-copy/`に同じフォルダをコピーします。Windowsではファイル操作でコピーしても使えます。

Claude Codeで次のように依頼します。

```text
/announcement-copy
この告知文を改善してください。
対象はAI初心者の個人事業主です。約4時間の対面実習です。
参加後の仕事でどう使うかが伝わるようにしてください。
［告知文と確定している開催条件を貼る］
```

新しく開いたセッションでスキルを確認してください。配置場所と呼び出し方は[Claude Code公式ドキュメント](https://code.claude.com/docs/en/skills)に基づきます。ローカルCLIでの実際の読み込みは、このリポジトリのテストでは確認していません。

## Codexで使う

`skills/announcement-copy/`を、使用環境で読み込むスキル用ディレクトリの`announcement-copy/`に配置します。たとえば`~/.codex/skills/announcement-copy/`です。既存の同名スキルは確認せず上書きしないでください。

```text
$announcement-copy を使って、この講座の告知文を作ってください。
［対象者、実習内容、日時・料金などを記載］
```

yomiyasuが使える環境では併用します。インストールされていない環境でも、読みやすい日本語で作業を進めます。yomiyasu自体は同梱していません。

## 画像も作る場合

```text
告知文に合う画像案を提案してください。
どのような構図・文字・サイズにするか、生成する前に確認してください。
```

スキルは、実際の作業例を見せる画像、内容を説明する図、見出し用のメイン画像などから、用途に合う案を出します。画像案の了承があってから生成します。実物の画面が必要なときは元画像を使い、架空の画面を実績として見せることはしません。

同梱CLIはOpenAI Images APIに対応しています。Python 3.10以上が必要です。外部Pythonパッケージは不要です。画像生成には`OPENAI_API_KEY`と、利用可能なモデル・API利用枠が必要です。API利用料金は各自で負担します。キーはローカルの環境変数に設定し、チャットやリポジトリへ書き込まないでください。

まず、画像計画を作業用フォルダにコピーして編集します。

```bash
mkdir -p output
cp skills/announcement-copy/examples/image-plan.json output/image-plan.json
python3 skills/announcement-copy/scripts/generate_image.py --plan output/image-plan.json
```

このコマンドは計画を表示するだけで、APIへ送信しません。表示された構図・文字・モデル・サイズ・画質・費用を確認し、了承後にだけ次を実行します。費用はプレビューでは算出しないため、実行前に[公式料金](https://developers.openai.com/api/docs/pricing)を確認します。

```bash
python3 skills/announcement-copy/scripts/generate_image.py \
  --plan output/image-plan.json \
  --execute --approved-sha256 承認した計画のSHA256
```

計画を変えるとSHA-256も変わり、前の値では実行できません。SHA-256の指定は、利用者が了承したことを自動で証明するものではありません。エージェントは会話での了承も確認します。

1回の実行でPNG画像を1枚生成します。保存先は計画ファイルからの相対パスです。実行記録も同じ場所に保存します。既存の画像・記録があれば停止し、失敗しても自動再送しません。画像編集や参照画像入力は未対応です。実行記録には生成指示を含むので、公開前に内容を確認してください。

例のモデルは`gpt-image-2`です。モデルの利用可否や制約は、実行前に[公式情報](https://developers.openai.com/api/docs/models/gpt-image-2)を確認してください。別の画像生成APIは同梱CLIでは未対応ですが、スキルは既存の対応ツールがある場合に仕様と条件を確認して使う方針です。詳細は[画像手順](skills/announcement-copy/references/images.md)を参照してください。

## 検証

```bash
python3 -m unittest discover -s tests -v
```

プレビュー時の無送信、計画変更後の承認無効化、レスポンスの保存、既存ファイルの保護、認証エラー、タイムアウト、自動再送の抑止を、モックで検証します。実際の有料API呼び出しや生成画像の見た目は、このテストの対象ではありません。

## 公開範囲

独自に整理した告知作成の指針、汎用の実装と例を公開しています。参考にした第三者の販売者名・商品名・出典URL・文章・画像・収集記録は同梱していません。スキルが作る告知本文や改善の説明、画像用の指示にも、これらの参照元情報を出さない方針です。MITライセンスの対象は本リポジトリで作成したファイルです。

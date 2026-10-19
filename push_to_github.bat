@echo off
chcp 65001 > nul
cd /d %~dp0
where git >nul 2>nul || (echo Git がインストールされていません。https://git-scm.com/download/win からインストールしてください。& pause & exit /b)
if exist ranking_workflow.yml (
  if not exist .github\workflows mkdir .github\workflows
  move /Y ranking_workflow.yml .github\workflows\ranking.yml > nul
)
git init -b main
git add -A
git commit -m "爆ハネランキング: 初期版"
git remote remove origin 2>nul
git remote add origin https://github.com/harashin96/BAKUHANE_KABU.git
git push -u origin main
echo.
echo 完了したら GitHub のページを開いて、ファイルが入っていることを確認してください。
pause

@echo off
chcp 65001 > nul
cd /d %~dp0
where git >nul 2>nul || (echo Git がインストールされていません。https://git-scm.com/download/win からインストールしてください。& pause & exit /b)
if exist ranking_workflow.yml (
  if not exist .github\workflows mkdir .github\workflows
  move /Y ranking_workflow.yml .github\workflows\ranking.yml > nul
)
if not exist .git git init -b main
git remote remove origin 2>nul
git remote add origin https://github.com/harashin96/BAKUHANE_KABU.git
git add -A
git commit -m "update"
rem GitHub側で毎日データが更新されるので、先にそれを取り込んでから送る
git pull --rebase origin main
git push -u origin main
echo.
echo 完了したら GitHub のページを開いて、更新されていることを確認してください。
pause

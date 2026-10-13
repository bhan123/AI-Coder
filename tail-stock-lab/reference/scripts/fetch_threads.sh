#!/usr/bin/env bash
# 批量抓取用户主帖 + 增量分页
set -u
COOKIE='sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219f366863251dcc-0deb240795ceb28-26061051-3686400-19f366863261d3e%22%7D; _HUPUSSOID=d36a2b97-0739-48bc-9db0-b9c9dc46db1d; u=18460199|aGlnaDNraWNr|aa90|78a02b89c1457c4b2bde9d2f0f1f4b49|6425f73e8418eaf4|aGlnaDNraWNr; ua=17854900; us=007e625022c23ffbefde1ae8f4a2f4fe4a70bf0c1c9adebf0389d0c437420e2496d6ea73dc994c115f5a8452b007a0d7b9bb9274ace034d73a8260649ac2b2e2; tfstk=gyMjF2OUMZbbXw-vWZ-yFThO-IesC3Je1GZtxcBVX-exXRitjPz4_Pl5fDoOg5L03AgSAlzYQ-k2CfwmUjWauE2sX2y68eJeLmm0nRLe8jgWz5w0flQYBNWRylw_DQosQki0IRLyIn26Sm0jycWgBRK7elENkREYB3a8YzBYXtEOy3ZgyRETBPURelZfkoEtW0K7jzUTBR3Te3ZgyPeTBv1GPlRbXmtZx-927wvs0z6OBYZJSkmf99EmLoGaJmHPBOILcSaKDzTVLyVUwcVsIGX_rmhnSk3AkFaiF0Hx92LPgrhQfDlsyh5sR4GLFxNPXeyqlYe-hSvhd2F_lbHYNGBtm8GY9fgXls4xg4N327I6KuuUymDxNhb-D2zbHuFypHi86bk0tx8RhJhn0-ltJU54kXZO4I6UREmP1gNhCuaeV31Gs0-TdJ0O6mLuMuqvL3t5P1VYquaeV31GsSEuDX-WVa1G.; _CLT=00376064be821b71351c003dda774e37; csrfToken=47Ul73Qf1y4Lpr8seve88KGv; acw_tc=707c9f6817854898955322671eb852e9e0aea6e5a677391f9f4993d999da98; _c_WBKFRo=MEkcU7Zpzr5edkK9XizvjDNNTqb73gEnt27KySwc; HMACCOUNT=BD59DA3FC1BDF7B1; Hm_lvt_ac423772552f47d0bb3ae6d55e13262c=1785490164; Hm_lpvt_ac423772552f47d0bb3ae6d55e13262c=1785490164'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
OUTDIR="/c/Users/36997/crawl/threads"
LOG="/c/Users/36997/crawl/fetch.log"

mkdir -p "$OUTDIR"
echo "" > "$LOG"

fetch_thread() {
    local tid="$1"
    local out="$OUTDIR/${tid}.html"
    if [ -s "$out" ]; then
        echo "SKIP $tid" | tee -a "$LOG"
        return 0
    fi
    local code
    code=$(curl -s -k -L -H "Cookie: $COOKIE" -H "User-Agent: $UA" -H "Referer: https://www.hupu.com/" -w "%{http_code}" -o "$out" "https://bbs.hupu.com/${tid}.html")
    local size=$(wc -c < "$out")
    echo "[$code] $tid  ${size}B" | tee -a "$LOG"
    if [ "$code" != "200" ] || [ "$size" -lt 1000 ]; then
        rm -f "$out"
    fi
    sleep 0.6
}

URL_FILE="$1"
shift || true
while IFS= read -r tid; do
    tid=$(echo "$tid" | grep -oE '[0-9]+' | head -1)
    [ -z "$tid" ] && continue
    fetch_thread "$tid"
done < "$URL_FILE"
echo "DONE"

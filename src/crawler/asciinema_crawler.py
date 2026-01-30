import os
import sys
import json
import threading
from urllib.parse import quote

from src.utils import *
from src.utils.http_utils import *

_hmrstr = hmrstr


def hmrstr(*args, **kwargs):
    return _hmrstr(*args, **kwargs).strip()


hd = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "cookie": "a758299=1; a758110=1; a757978=1; a480042=1; a480048=1; a758167=1; a746358=1; _asciinema_key=SFMyNTY.g3QAAAABbQAAAAtfY3NyZl90b2tlbm0AAAAYYXZyTE5rdFc0dmFBc040eWs5S09nWVo3.GrOocY4sDPa9mAdCGIlnEQ44okwTS3KFSYABj_4aeus; a759172=1; a759173=1",
    "pragma": "no-cache",
    "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="101", "Google Chrome";v="101"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.0.0 Safari/537.36",
}


def getdata(svp, url, ref):
    rows = []
    code = []
    cdx = gethtml(url, ref, hads=hd, cods=code, pxy=poxy)
    if code != [200]:
        print("Skip")
        return
    we(svp[:-3] + "html", cdx, "wb")

    we(svp[:-3] + "txt", gethtml(url + ".txt", url, hads=hd, pxy=poxy), "wb")
    we(svp[:-3] + "cast", gethtml(url + ".cast", url, hads=hd, pxy=poxy), "wb")
    cdx = cn(cdx)

    trs = strfml(cdx, '"even info"', "")
    ls = ["" for i in rls]
    ls[rls.index("url")] = url
    ls[rls.index("title")], trs[1] = strfml(cdx, "<h2>", "</h2>", trs[1])

    sm, trs[1] = strfml(cdx, "<small>", "</small>", trs[1])
    if trs[1] > -1:
        ls[rls.index("name")] = hmrstr(strfml(sm, "by", "</a>")[0])
        ls[rls.index("profile_url")] = (
            "https://asciinema.org" + strfml(sm, 'href="', '"')[0]
        )
        ls[rls.index("date")] = strfml(sm, 'datetime="', '"')[0]

    sm, trs[1] = strfml(cdx, '"odd meta"', "</section>", trs[1])
    if trs[1] > -1:
        hst = strfml(sm, '"status-line-item"', "")[1]
        _s = hmrstr(strfml(sm, ">", '<span class="status', hst)[0]).split("◆")
        for i in range(len(_s)):
            ls[rls.index("system") + i] = _s[i].strip()
        hst = strfml(sm, '"Total views"', "", hst)[1]
        ls[rls.index("views")] = hmrstr(strfml(sm, ">", "</div>", hst)[0]).replace(
            "views", ""
        )

        hst = strfml(sm, '"description"', "", hst)[1]
        ls[rls.index("description")] = strfml(sm, ">", "</div>", hst)[0]

    rows.append(ls)
    we(svp, rows, ecd="u8")


def getye(i):
    url = "https://asciinema.org/explore/public?order=date&page=" + str(i)
    ref = None
    if i > 1:
        ref = "https://asciinema.org/explore/public?order=date&page=" + str(i - 1)
    idx = cn(gethtml(url, ref, hads=hd, pxy=poxy))

    # we("3.txt",idx,"wb")

    ref = url
    task_list = []
    trs = ["", 0]
    while 1:
        trs = strfml(idx, '"asciicast-card"', "", trs[1])
        if trs[1] < 0:
            break
        # print(j["reportId"])

        url = strfml(idx, 'href="', '"', trs[1])[0]
        id = strfml(url + "^H^", "a/", "^H^")[0]
        # svp=ddddir+"\\{}_{}.csv".format(i,id)
        svp = ddddir + "\\{}.csv".format(id)

        if os.path.exists(svp):
            continue
        url = "https://asciinema.org" + url
        task_list.append(threading.Thread(target=getdata, args=[svp, url, ref]))

    if task_list != []:
        setaskN(task_list, len(task_list))
        time.sleep(0.6)


def main():
    task_list = []
    # Page
    for i in range(1, 5736):
        print(i, "Page")
        task_list.append(threading.Thread(target=getye, args=[i]))
        if i % 8 == 0:
            setaskN(task_list, 8)
            task_list.clear()
    setaskN(task_list, 8)
    # exit()


if __name__ == "__main__":
    rls = [
        "name",
        "profile_url",
        "date",
        "description",
        "system",
        "terminal",
        "shell",
        "title",
        "url",
        "views",
    ]
    poxy = "http://127.0.0.1:7890"

    ddddir = "Data"
    if not os.path.exists(ddddir):
        os.mkdir(ddddir)
    main()
    input("Press Enter to exit...")
    exit()

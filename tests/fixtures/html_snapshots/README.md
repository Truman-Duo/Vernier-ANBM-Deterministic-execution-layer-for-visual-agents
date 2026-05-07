# HTML Snapshots

用于 `FakePage.from_html()` 加载的页面 HTML 快照。每个文件仅包含被测选择器对应的最小 DOM 片段，不包含完整页面样式和脚本。

| 文件路径 | 来源 URL | 构造时间 | 覆盖场景 |
|---------|---------|---------|---------|
| `douban_movie/movie_list.html` | `https://movie.douban.com/top250` | 2026-04-29 | movie_list 状态检测、`ol.grid_view` 选择器、title/rating/url 字段提取 |
| `hackernews/news_list.html` | `https://news.ycombinator.com/news` | 2026-04-29 | news_list 状态检测、`tr.athing` 选择器、`td.subtext` 中的 score/author 字段、`a.morelink` 翻页 |
| `hackernews/item_detail.html` | `https://news.ycombinator.com/item?id=47936347` | 2026-04-29 | item_detail 状态检测、`tr.comtr` 嵌套评论提取（层级 0-3）、`td.ind > img[width]` 缩进计算、`a.hnuser` 作者、`div.commtext` 正文 |
| `wikipedia/article.html` | `https://en.wikipedia.org/wiki/Web_scraping` | 2026-04-29 | article 状态检测、`h1#firstHeading` 标题、`div.mw-parser-output` 正文、`h2` 章节、`a.interlanguage-link-target` 语言链接 |

所有快照手动构造，不依赖网络访问。

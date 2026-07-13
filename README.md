# techai Google Index Page

This folder is ready to publish as a GitHub Pages site.

## Target

- Naver Blog: https://blog.naver.com/techai
- Indexable post source links: https://m.blog.naver.com/techai/{logNo}
- Recommended repository name: `techai-google-index`
- Expected Pages URL: `https://techai-n.github.io/techai-google-index/`

## Publish Steps

1. Re-authenticate GitHub CLI or create the repository manually on GitHub.
2. Create a public GitHub repository named `techai-google-index`.
3. Upload these files to the repository root:
   - `index.html`
   - `robots.txt`
   - `sitemap.xml`
   - `posts/`
4. In GitHub, open `Settings` > `Pages`.
5. Set source to `Deploy from a branch`, branch `main`, folder `/root`.
6. Open Google Search Console and add the Pages URL property:
   - `https://techai-n.github.io/techai-google-index/`
7. Verify ownership using the HTML file or meta tag Google provides.
8. Submit this sitemap:
   - `https://techai-n.github.io/techai-google-index/sitemap.xml`
9. Use URL Inspection for:
   - `https://techai-n.github.io/techai-google-index/`

## Update Posts

The `Update blog index` GitHub Actions workflow runs every day at 00:00 KST.
It reads the public Naver RSS feed, adds newly published post pages, and keeps
the main index and sitemap in sync. It can also be run manually from the
repository's `Actions` tab.

To run the same updater locally:

```bash
python3 scripts/update_index.py
```

Each generated post page should keep:

- a self-canonical GitHub Pages URL
- `index, follow`
- source links pointing to `https://m.blog.naver.com/techai/{logNo}`
- the GitHub Pages URL in `sitemap.xml`

import sys
import requests
import re
import urllib.parse
import html

def clean_html(raw_html):
    # Remove tags
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    # Decode HTML entities
    return html.unescape(cleantext).strip()

def search(query):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    url = "https://html.duckduckgo.com/html/"
    data = {'q': query}
    
    try:
        response = requests.post(url, data=data, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Error performing search: {e}")
        return

    page_content = response.text
    
    # Split by result div
    # Typical structure: <div class="result results_links ...">
    # We split by the start of this tag
    results_blocks = re.split(r'<div[^>]*class="[^"]*result\s+results_links[^"]*"[^>]*>', page_content)
    
    final_results = []
    
    # Skip the first chunk which is header
    for block in results_blocks[1:]:
        # Extract title and link: <a class="result__a" href="...">...</a>
        link_match = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
        
        if link_match:
            link = link_match.group(1)
            title = clean_html(link_match.group(2))
            
            if "/l/?uddg=" in link:
                try:
                    parsed = urllib.parse.urlparse(link)
                    qs = urllib.parse.parse_qs(parsed.query)
                    if 'uddg' in qs:
                        link = qs['uddg'][0]
                except:
                    pass

            # Extract snippet: <a class="result__snippet" ...>...</a>
            snippet = ""
            snippet_match = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
            if snippet_match:
                snippet = clean_html(snippet_match.group(1))
            
            final_results.append({'title': title, 'link': link, 'snippet': snippet})
            if len(final_results) >= 5:
                break
    
    if not final_results:
        print("No results found.")
        return

    print(f"Top results for: {query}\n")
    for i, res in enumerate(final_results):
        print(f"{i+1}. {res['title']}")
        print(f"   Link: {res['link']}")
        print(f"   Snippet: {res['snippet']}")
        print("-" * 40)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python web_search.py <query>")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    search(query)

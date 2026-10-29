"""Validate bilingual reader navigation, return routes and local Markdown links."""
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r'(?<!!)\[([^\]]+)\]\(([^ )]+)(?: +"[^"]*")?\)')


def prose(body):
    """Ignore both Markdown fence styles before inspecting headings and links."""
    lines=[]; fence=None
    for line in body.splitlines():
        match=re.match(r'^\s*([`~]{3,})',line)
        if match and len(set(match[1]))==1:
            if fence is None:
                fence=match[1];continue
            if match[1][0]==fence[0] and len(match[1])>=len(fence):
                fence=None;continue
        if fence is None:lines.append(line)
    return '\n'.join(lines)


def anchors(body):
    text=prose(body)
    found=set(re.findall(r'<a\s+(?:id|name)=[\"\x27]([^\"\x27]+)',text))
    counts={}
    for heading in re.findall(r'^#{1,6}\s+(.+?)\s*#*$',text,re.M):
        heading=re.sub(r'<[^>]*>','',heading)
        slug=re.sub(r'[^\w\- ]','',heading.lower()).replace(' ','-')
        index=counts.get(slug,0);candidate=slug if not index else slug+'-'+str(index)
        while candidate in found:
            index+=1;candidate=slug+'-'+str(index)
        counts[slug]=index+1;found.add(candidate)
    return found


def local_links():
    tracked=set(filter(None,subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode('utf8').split('\0')))
    documents=sorted(name for name in tracked if name.endswith('.md') and not name.startswith('LICENSES/'))
    errors=[];checked=0
    for name in documents:
        for _,href in LINK.findall(prose((ROOT/name).read_text(encoding='utf8'))):
            parsed=urlsplit(href)
            if parsed.scheme or parsed.netloc:continue
            checked+=1
            target=(posixpath.normpath(posixpath.join(str(PurePosixPath(name).parent),unquote(parsed.path)))
                    if parsed.path else name)
            path=(ROOT/target).resolve()
            if not path.is_relative_to(ROOT):
                errors.append(name+': link escapes repository: '+href);continue
            if target not in tracked and not any(p.startswith(target.rstrip('/')+'/') for p in tracked):
                errors.append(name+': missing/untracked or case-mismatched target: '+href);continue
            if parsed.fragment and path.suffix=='.md':
                fragment=unquote(parsed.fragment).removeprefix('user-content-')
                if fragment not in anchors(path.read_text(encoding='utf8')):
                    errors.append(name+': missing heading anchor: '+href)
    return documents,checked,errors


def links(name):
    body = prose((ROOT/name).read_text(encoding='utf8'))
    result = []
    for label, href in LINK.findall(body):
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc:
            continue
        if not parsed.path:
            target = (ROOT/name).resolve()
        else:
            target = (ROOT/Path(name).parent/unquote(parsed.path)).resolve()
        if not target.is_relative_to(ROOT):
            result.append((label, None))
        else:
            result.append((label, target.relative_to(ROOT).as_posix()))
    return result


def check():
    documents,link_count,errors=local_links()
    sys.path.insert(0,str(ROOT))
    from tools.build_readme_prompts import update
    for filename in update(check=True):
        errors.append(filename+': homepage prompt differs from its guide; run tools/build_readme_prompts.py')
    locales = {'en': 'README.md', 'zh': 'README.zh-CN.md'}
    pages = {lang: {p.name for p in (ROOT/'docs'/lang).glob('*.md')} for lang in locales}
    if pages['en'] != pages['zh']:
        errors.append('English and Chinese topics do not match.')
    checked = set(locales.values())
    checked.update('docs/'+lang+'/'+name for lang, names in pages.items() for name in names)
    graph = {}
    for lang, home in locales.items():
        other = 'zh' if lang == 'en' else 'en'
        own = {home} | {'docs/'+lang+'/'+name for name in pages[lang]}
        for name in sorted(own):
            counterpart = locales[other] if name == home else 'docs/'+other+'/'+Path(name).name
            lines = (ROOT/name).read_text(encoding='utf8').strip().splitlines()
            prefix = (r'^\*\*简体中文\*\* \| \[English\]\([^)]+\) · '
                      if lang == 'zh' else r'^\[简体中文\]\([^)]+\) \| \*\*English\*\* · ')
            if not all(re.match(prefix, line) for line in (lines[2], lines[-1])):
                errors.append(name+': language selector must lead both navigation bars, Chinese then English')
            parsed = links(name)
            graph[name] = set()
            for label, target in parsed:
                if target is None or not (ROOT/target).exists():
                    errors.append(name+': missing/escaping link '+str(target))
                    continue
                if target in own:
                    graph[name].add(target)
                    continue
                if target == counterpart and label in ('English', '简体中文'):
                    continue
                # Machine instructions may be linked explicitly, never presented as a reader chapter.
                if target == 'AGENTS.md' and 'Agent' in label and (lang == 'en' or '英文' in label):
                    continue
                if PurePosixPath(target).suffix == '.md':
                    errors.append(name+': unexpected language/document jump to '+target)
            if not any(target == counterpart and label in ('English', '简体中文')
                       for label, target in parsed):
                errors.append(name+': missing same-topic language switch')
            if name != home:
                # Header and footer both provide a way back after a long page.
                for target in (home, 'docs/'+lang+'/index.md'):
                    if sum(t == target for _, t in parsed) < 2:
                        errors.append(name+': missing header/footer return link to '+target)
        seen = set()
        stack = [home]
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            stack.extend(graph.get(name, ()))
        if seen != own:
            errors.append(lang+': pages unreachable without language switching: '+str(sorted(own-seen)))
        index = 'docs/'+lang+'/index.md'
        if own-{home, index}-graph.get(index, set()):
            errors.append(lang+': documentation index is incomplete')
    return {'reader_pages': len(checked), 'paired_topics': len(pages['en']),
            'markdown_files':len(documents),'local_links_checked':link_count,
            'passed': not errors, 'errors': errors}


if __name__ == '__main__':
    import json
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(not result['passed'])

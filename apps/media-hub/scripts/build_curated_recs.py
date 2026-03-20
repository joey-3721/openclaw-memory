import json, requests, re
import app

CURATED = [
    ('movie', 'Dune: Part Two', '沙丘2', '一个注定要走上神坛的人，明知道前面是权力、宗教和血债缠成的深渊，还是只能继续往前。它最容易让人上头的，就是你会一直想看他什么时候彻底跨过那条回不去的线。'),
    ('movie', 'Kingdom of the Planet of the Apes', '猩球崛起：王国诞生', '它不是简单的怪物或动作片，而是在讲旧文明倒下之后，新秩序会不会长成另一种暴政。那种世界刚被改写、规则还在流血的感觉，很容易把人拖进去。'),
    ('movie', 'Furiosa: A Mad Max Saga', '疯狂的麦克斯：狂暴女神', '这不是一部温吞的成长片，而是看一个被掠走人生的人，怎么在废土里把自己活活炼成武器。节奏一路往前顶，几乎不给你分神的机会。'),
    ('movie', 'Alien: Romulus', '异形：夺命舰', '密闭空间、未知生物、没有退路——这种故事最狠的地方，是你会眼看着所有人一步步被逼到极限。它不是慢热型，会很快把你拉进那种“完了，要出事”的高压里。'),
    ('movie', 'Joker: Folie à Deux', '小丑2：双重妄想', '如果你对“一个人怎么被世界一步步推向疯狂”这种故事有兴趣，这部会有吸引力。你会忍不住看他还能把现实撕裂到什么程度。'),
    ('movie', 'Deadpool & Wolverine', '死侍与金刚狼', '如果你现在想看一部节奏快、嘴够损、打得也够狠的片，这部很稳。它那种互相嫌弃却被迫绑在一起的化学反应，天生就适合一口气看完。'),
    ('movie', 'The Substance', '某种物质', '它不是单纯猎奇，而是把衰老、欲望和自我吞噬拍到越来越失控。你会好奇这件事到底还能恶化到什么程度，这种一路滑向崩坏的感觉很容易让人停不下来。'),
    ('movie', 'Mickey 17', '编号17', '一个人被当成可反复消耗的替代品，本身就已经够带劲了。更狠的是，它把荒诞感和生存焦虑拧在一起，让你越看越想知道他最后会怎么反咬这个系统。'),
    ('tv', 'Shōgun', '幕府将军', '它厉害的地方不是热闹，而是所有人表面都很克制，底下每一句话都像刀。那种礼貌外壳包着杀局的权谋感，非常适合慢慢陷进去。'),
    ('tv', 'Tokyo Vice', '东京罪恶', '一个外来者闯进东京地下世界，越查越深，越陷越危险。它不是靠大场面取胜，而是那种“你已经进来了，现在退不出去”的沉浸感特别强。'),
    ('tv', 'A Killer Paradox', '杀人者的难堪', '一个普通人意外杀了人，真正可怕的不是案件，而是他发现自己可能停不下来了。你会一直想看，这个人到底会坏到什么程度。'),
    ('tv', 'The Glory', '黑暗荣耀', '复仇最上头的从来不是结果，而是准备过程。你会想看她怎么一点点收网，把那些看似稳固的人生一个个拖进自己设计好的局里。'),
    ('tv', 'Queen of Tears', '泪之女王', '它不是简单的甜，而是两个人明明快走散了，却又不断被命运和现实拽回彼此身边。那种情感拉扯感很强，很容易越看越上头。'),
    ('tv', '3 Body Problem', '三体', '它真正抓人的不是科幻名词，而是那种文明尺度的寒意慢慢压下来。你会越看越想知道，人类到底是从什么时候开始失去安全感的。'),
    ('tv', 'Stranger Things', '怪奇物语', '小镇、怪物、裂缝、失踪案，它很懂怎么一层层把气氛往上拉。群像也立得住，所以非常容易一集接一集刷下去。'),
    ('tv', 'Brush Up Life', '重启人生', '表面轻松，骨子里却很会写人生岔路和人与人之间那种微妙变化。它不是刺激型，但特别有那种“再看一集吧”的后劲。'),
    ('tv', 'Love in the Big City', '大都市的爱情法', '它不是轻飘飘的都市爱情，而是把靠近、误解、错过和孤独都拍得很贴。你会想看这些人最后到底能不能从彼此身上找到一点真心。'),
    ('tv', 'Culinary Class Wars', '黑白厨师：料理阶级大战', '它最上头的不是做菜，而是高手之间那种谁都不服谁的压迫感。看谁能在最短时间里证明自己，天然就会让人想一直看下去。'),
    ('tv', 'Physical: 100', '体能之巅：百人大挑战', '所有人都强，但最后一定有人更狠。这种把肉体极限一轮轮压出来的节目，最容易让人不知不觉连着刷。'),
    ('tv', 'Street Woman Fighter', '街头女战士', '它不只是跳舞，更像一群高手把风格、尊严和胜负欲全摆到台面上正面对撞。那种“谁也不服谁”的劲，很难不让人继续看。'),
]


def pick_result(results, zh_title=None):
    if not results:
        return None
    if zh_title:
        for r in results:
            title = (r.get('title') or r.get('name') or '').strip()
            if zh_title in title:
                return r
    # prefer Chinese title if present
    for r in results:
        title = (r.get('title') or r.get('name') or '').strip()
        if re.search(r'[\u4e00-\u9fff]', title):
            return r
    return results[0]


def main():
    conn = app.get_conn()
    key = app.read_tmdb_key()
    proxies = {'http': 'http://192.168.50.209:7890', 'https': 'http://192.168.50.209:7890'}
    items = []
    for media, en_query, zh_title, reason in CURATED:
        url = f'https://api.themoviedb.org/3/search/{media}'
        try:
            resp = requests.get(url, params={'api_key': key, 'query': en_query, 'language': 'zh-CN', 'include_adult': 'false'}, proxies=proxies, timeout=25)
            data = resp.json()
        except Exception as e:
            print('ERR', zh_title, e)
            continue
        raw = pick_result(data.get('results') or [], zh_title)
        if not raw:
            print('MISS', zh_title)
            continue
        item = app.tmdb_to_item(raw, media)
        item['title'] = zh_title if zh_title else item.get('title')
        item['_reason'] = reason
        item['_score'] = 100 - len(items)
        item['_cover_style'] = app.cover_style(item)
        item['_cover_url'] = app.cover_url(item)
        item['_stars'] = app.rating_stars(item.get('douban_rating'))
        item['_first_genre'] = app.first_genre(item)
        items.append(item)
        print('OK', item['title'])
    app.cache_recommendations(conn, items[:20], cache_key='default')
    cached = app.load_cached_recommendations(conn, cache_key='default', max_age_hours=9999)
    print('cached_count', len(cached))
    print([x.get('title') for x in cached])

if __name__ == '__main__':
    main()

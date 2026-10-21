"""淘金币「双11狂享20亿」——金币任务流程（去赚金币）。

活动入口：淘宝首页搜索「淘金币双11狂享20亿」-> H5 活动页
任务面板：活动页左下角「去赚金币」-> 弹出「赚金币抵钱」面板

和 618 版最大的区别：
- 活动页是 H5（Themis 容器），主页面用 canvas 渲染，拿不到文案，只能用相对坐标点入口；
- 任务面板是正常 DOM，用「文案 + 几何位置」解析每张任务卡片；
- 任务有次数（0/3、0/5），做完一次卡片不会消失，需要重复直到次数满；
- 需要跳转支付宝/头条的任务跳过。
"""
import logging
import re
import time

from modules import activity, ui
from modules.utils import mute

logger = logging.getLogger(__name__)

# 浏览类任务停留秒数（活动要求 15s/5s，页面加载和倒计时都有延迟，留足余量）
BROWSE_SECONDS = {'15': 20, '5': 10}

MAX_ROUNDS = 80          # 总轮数上限，防止死循环
EXTRA_ATTEMPTS = 2       # 每个任务在所需次数之外允许多试几次

CLAIM_BTNS = ('领取奖励', '去领取')
ENTRY_LABEL = '去赚金币'


def _panel_open(nodes):
    return bool(ui.parse_tasks(nodes))


def _required_count(name):
    """从 '发现精选好物(0/3)' 里取出总次数 3。"""
    m = re.search(r'\((\d+)\s*/\s*(\d+)\)', name)
    return int(m.group(2)) if m else 1


def _task_key(name):
    """去掉 (0/3) 这种进度后缀，作为任务的稳定标识。"""
    key = re.sub(r'\(\s*\d+\s*/\s*\d+\s*\)', '', name).strip()
    return key or '未知任务'


def _pick_claim(tasks):
    for t in tasks:
        if t['btn'] in CLAIM_BTNS:
            return t
    return None


def _pick_browse(tasks, attempts):
    """挑一个能自动完成的浏览任务（跳过需要跳转外部 App 的）。"""
    for t in tasks:
        if t['btn'] != '去完成':
            continue
        if '浏览' not in t['desc']:
            # 新版面板部分浏览任务没有描述文案，按任务名兜底判断
            if not (not t['desc'] and ('逛' in t['name'] or '浏览' in t['name'])):
                logger.debug('跳过非浏览任务：%s（%s）', t['name'], t['desc'])
                continue
        key = _task_key(t['name'])
        limit = _required_count(t['name']) + EXTRA_ATTEMPTS
        if attempts.get(key, 0) >= limit:
            logger.info('任务「%s」已尝试 %d 次，跳过', key, attempts[key])
            continue
        return t
    return None


def _browse_wait(desc):
    for key, seconds in BROWSE_SECONDS.items():
        if key in desc:
            return seconds
    return 20


def do_browse(d, task):
    """执行一次浏览任务：点按钮 -> 按类型浏览（滑动计时）-> 返回。成功返回 True。"""
    logger.info('执行任务：%s（%s）', task['name'], task['desc'])
    wait = _browse_wait(task['desc'])
    logger.info('浏览中，停留 %d 秒', wait)
    return activity.run_browse_task(d, task, wait, _panel_titles(), ui.parse_tasks)


def do_claim(d, task):
    logger.info('领取任务奖励：%s', task['name'])
    ui.tap_node(d, task['node'])
    time.sleep(2.5)


def claim_cumulative(d, nodes):
    """领取 3/10/20 次任务的累计奖励（达标后按钮文案变成「立即领取」）。"""
    claimed = 0
    for btn in ui.find_nodes(nodes, text='立即领取'):
        logger.info('领取累计奖励（当前进度 %s）', activity.progress(nodes))
        ui.tap_node(d, btn)
        time.sleep(1.8)
        claimed += 1
    return claimed


def _panel_titles():
    return activity.COIN_PANEL


def _find_actionable(d, attempts):
    """在整个面板里找可执行任务（自动滚动，覆盖屏幕外的任务）。"""
    return activity.find_task_all(d, _panel_titles(), ui.parse_tasks,
                                  lambda tasks: _pick_browse(tasks, attempts))


def _is_coin_v2(nodes):
    """新版金币面板（今日速赚淘金币：额外得金币 + 更多金币等你赚）。"""
    return any('更多金币等你赚' in (n['text'] or '') for n in nodes)


def ask_extra_coins():
    """询问是否先执行顶部「额外得金币」任务。"""
    print()
    print('╔══════════════════════════════════════════╗')
    print('║  检测到「额外得金币」任务                ║')
    print('╠══════════════════════════════════════════╣')
    print('║ 1. 先执行额外得金币任务（默认）          ║')
    print('║ 2. 跳过，只做下方「更多金币等你赚」      ║')
    print('╚══════════════════════════════════════════╝')
    while True:
        choice = input('请选择 (1-2，默认1): ').strip()
        if choice in ('', '1'):
            return True
        if choice == '2':
            return False
        print('无效选择，请输入1或2')


def do_extra_rows(d, max_tasks=8):
    """执行顶部「额外得金币」里的浏览类任务（点标题进入，回来徽章会变√）。"""
    done = 0
    attempts = {}
    for _ in range(max_tasks):
        nodes = activity.ensure_panel(d, activity.COIN_PANEL, activity.COIN_ENTRY, ENTRY_LABEL)
        if not nodes:
            break
        rows = [r for r in ui.parse_coin_rows(nodes) if r['action'] == 'browse']
        if not rows:
            logger.info('额外得金币里没有可执行的浏览任务了')
            break

        row = None
        for r in rows:
            key = r['name']
            if attempts.get(key, 0) < 2:
                row = r
                break
        if not row:
            break

        attempts[row['name']] = attempts.get(row['name'], 0) + 1
        logger.info('额外任务：%s（%s）', row['name'], row['desc'])
        ui.tap_node(d, row['node'])
        time.sleep(2.5)
        activity.browse_page(d, (row['seconds'] or 15) + 5)

        d.go_back()
        time.sleep(2.5)
        if not activity.on_activity(d, tries=1):
            d.go_back()
            time.sleep(2)
        done += 1
    return done


def expand_more_coins(d):
    """展开「更多金币等你赚」并向下滚动，露出完整任务清单。"""
    nodes = activity.ensure_panel(d, activity.COIN_PANEL, activity.COIN_ENTRY, ENTRY_LABEL) or []
    if not any('更多金币等你赚' in (n['text'] or '') for n in nodes):
        return False
    exp = [n for n in nodes if '展开' in (n['text'] or '')]
    if not exp:
        return False
    logger.info('展开「更多金币等你赚」')
    ui.tap_node(d, exp[0])
    time.sleep(2)
    activity.scroll_panel(d, 'up')
    return True


def run(d, mode='auto', keyword=activity.KEYWORD):
    """执行金币任务，返回结果摘要字符串。"""
    logger.info('开始运行金币任务')
    activity.prepare_device(d)
    mute(d)
    activity.enter_activity(d, mode, keyword)

    done = 0
    claimed = 0
    attempts = {}

    # 新版金币面板：先问是否做「额外得金币」，再展开「更多金币等你赚」
    first = activity.ensure_panel(d, activity.COIN_PANEL, activity.COIN_ENTRY, ENTRY_LABEL)
    if first and _is_coin_v2(first):
        logger.info('检测到新版金币面板（今日速赚淘金币）')
        if ask_extra_coins():
            done += do_extra_rows(d)
        expand_more_coins(d)

    for round_no in range(1, MAX_ROUNDS + 1):
        nodes = activity.ensure_panel(d, activity.COIN_PANEL, activity.COIN_ENTRY, ENTRY_LABEL)
        if not nodes:
            raise RuntimeError('金币任务面板打不开，请确认活动页面是否正常')

        tasks = ui.parse_tasks(nodes)
        logger.info('第 %d 轮：面板任务 %d 个 完成进度 %d', round_no, len(tasks),
                    activity.progress(nodes))
        for t in tasks:
            logger.debug('  · %s | %s | %s', t['name'], t['desc'], t['btn'])

        # 累计奖励（3/10/20 次）先领，避免奖励入口被挤掉
        n_claim = claim_cumulative(d, nodes)
        if n_claim:
            claimed += n_claim
            continue

        claim = _pick_claim(tasks)
        if claim:
            try:
                do_claim(d, claim)
                claimed += 1
            except Exception as e:
                logger.warning('领取奖励失败: %s', e)
            continue

        # 当前屏没有可执行任务时，滚动面板继续找（下方还有任务）
        task, nodes = _find_actionable(d, attempts)
        if not task:
            # 面板任务会动态刷新，关掉重开再识别一次
            logger.info('面板内没有可执行任务，关闭重开刷新任务列表')
            activity.close_panel(d)
            nodes = activity.ensure_panel(d, activity.COIN_PANEL, activity.COIN_ENTRY, ENTRY_LABEL)
            task, nodes = _find_actionable(d, attempts) if nodes else (None, None)
        if not task:
            logger.info('没有可自动完成的浏览任务')
            break

        key = _task_key(task['name'])
        attempts[key] = attempts.get(key, 0) + 1
        try:
            if do_browse(d, task):
                done += 1
        except Exception as e:
            logger.warning('任务「%s」执行失败: %s', key, e)
            time.sleep(2)

    # 收尾：再领一次累计奖励
    try:
        claimed += claim_cumulative(d, ui.dump_panel(d, activity.COIN_PANEL) or [])
    except Exception as e:
        logger.warning('累计奖励领取异常: %s', e)

    logger.info('金币任务执行完毕：共完成 %d 次浏览任务，领取 %d 次奖励', done, claimed)
    return f'{done}次浏览/{claimed}次领奖'

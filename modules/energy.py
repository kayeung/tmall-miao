"""淘金币「双11狂享20亿」——能量任务流程（去赚能量）。

活动入口：淘宝首页搜索「淘金币双11狂享20亿」-> H5 活动页
任务面板：活动页右下角「去赚能量」-> 弹出「做任务赚能量」面板

能量面板与金币面板的区别：
- 卡片文案把「任务名(x/n) + 动作 + 奖励」挤在同一个 TextView 里，例如
  「好物随心逛(0/10)浏览15秒+400」，所以要用 parse_energy_tasks 解析；
- 所有卡片按钮都叫「去完成」，动作类型只能从文案判断（浏览/点击去逛/答题）；
- 累计奖励是 5/20/50 次，入口是可点击的 View（「5次任务，最高，奖励1000」）。
"""
import logging
import time

from modules import activity, ui
from modules.utils import mute

logger = logging.getLogger(__name__)

BROWSE_SECONDS = {'15': 20, '5': 10}

MAX_ROUNDS = 120
EXTRA_ATTEMPTS = 2

ENTRY_LABEL = '去赚能量'
CLAIM_BTNS = ('领取奖励', '去领取')

# 累计奖励：(需要的完成次数, 文案关键字)
CUMULATIVE_REWARDS = ((5, '5次任务'), (20, '20次任务'), (50, '50次任务'))


def _pick_claim(tasks):
    for t in tasks:
        if t['btn'] in CLAIM_BTNS:
            return t
    return None


def _pick_browse(tasks, attempts):
    """挑一个能自动完成的浏览任务；跳过去支付宝/头条和答题类。"""
    for t in tasks:
        if t['action'] != 'browse':
            if t['action'] in ('external', 'quiz'):
                logger.debug('跳过任务：%s（%s）', t['name'], t['desc'])
            continue
        key = t['base']
        limit = max(t['total'], 1) + EXTRA_ATTEMPTS
        if attempts.get(key, 0) >= limit:
            logger.info('任务「%s」已尝试 %d 次，跳过', key, attempts[key])
            continue
        return t
    return None


def _browse_wait(task):
    seconds = task.get('seconds') or 15
    for key, wait in BROWSE_SECONDS.items():
        if str(seconds) == key:
            return wait
    return 20


def do_browse(d, task):
    """执行一次浏览任务：点按钮 -> 按类型浏览（滑动计时）-> 返回。"""
    logger.info('执行任务：%s（%s）', task['name'], task['desc'])
    wait = _browse_wait(task)
    logger.info('浏览中，停留 %d 秒', wait)
    activity.run_browse_task(d, task['node'], wait)


def claim_cumulative(d, nodes, claimed):
    """领取 5/20/50 次任务的累计奖励（达标且未领过才点）。"""
    prog = activity.progress(nodes, '当前进度')
    for need, keyword in CUMULATIVE_REWARDS:
        if need in claimed or prog < need:
            continue
        cands = [n for n in nodes if keyword in n['text'] and n['clickable']]
        if not cands:
            continue
        if any('已领' in n['text'] for n in cands):
            claimed.add(need)
            continue
        logger.info('领取累计奖励「%s」（当前进度 %d/50）', keyword, prog)
        ui.tap_node(d, cands[0])
        claimed.add(need)
        time.sleep(1.8)


def _find_actionable(d, attempts):
    """在整个面板里找可执行任务（自动滚动，覆盖屏幕外的任务）。"""
    return activity.find_task_all(d, activity.ENERGY_PANEL, ui.parse_energy_tasks,
                                  lambda tasks: _pick_browse(tasks, attempts))


def run(d, mode='auto', keyword=activity.KEYWORD):
    """执行能量任务，返回结果摘要字符串。"""
    logger.info('开始运行能量任务')
    mute(d)
    activity.enter_activity(d, mode, keyword)

    done = 0
    claimed_tasks = 0
    claimed_total = set()
    attempts = {}
    scrolled = False

    for round_no in range(1, MAX_ROUNDS + 1):
        nodes = activity.ensure_panel(d, activity.ENERGY_PANEL, activity.ENERGY_ENTRY, ENTRY_LABEL)
        if not nodes:
            raise RuntimeError('能量任务面板打不开，请确认活动页面是否正常')

        tasks = ui.parse_energy_tasks(nodes)
        logger.info('第 %d 轮：面板任务 %d 个 当前进度 %d/50', round_no, len(tasks),
                    activity.progress(nodes, '当前进度'))
        for t in tasks:
            logger.debug('  · %s | %s | %s', t['name'], t['desc'] or t['action'], t['btn'])

        before = len(claimed_total)
        claim_cumulative(d, nodes, claimed_total)
        if len(claimed_total) > before:
            continue

        claim = _pick_claim(tasks)
        if claim:
            try:
                logger.info('领取任务奖励：%s', claim['name'])
                ui.tap_node(d, claim['node'])
                claimed_tasks += 1
                time.sleep(2)
            except Exception as e:
                logger.warning('领取奖励失败: %s', e)
            continue

        task = _pick_browse(tasks, attempts)
        if not task:
            logger.info('没有可自动完成的浏览任务')
            if not scrolled:
                _scroll_panel(d)
                scrolled = True
                continue
            break

        scrolled = False
        attempts[task['base']] = attempts.get(task['base'], 0) + 1
        try:
            do_browse(d, task)
            done += 1
        except Exception as e:
            logger.warning('任务「%s」执行失败: %s', task['base'], e)
            time.sleep(2)

    logger.info('能量任务执行完毕：共完成 %d 次浏览任务，领取 %d 次任务奖励、%d 个累计奖励',
                done, claimed_tasks, len(claimed_total))
    return f'{done}次浏览/{len(claimed_total)}个累计奖'

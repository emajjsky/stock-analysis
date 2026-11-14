"""只读研究资料缓存；获知时点、版本及失败保留与行情/交易隔离。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import threading
import uuid

from backend.providers import ProviderError, normalize_security_id

SECTIONS = ('company', 'financials', 'announcements')
LABELS = {'company': '公司概况', 'financials': '财务摘要', 'announcements': '公告目录'}


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def canonical(security_id):
    return normalize_security_id(security_id.removeprefix('LIVE.'))[0]


class ResearchData:
    provider_id = 'eastmoney-research'
    limitations = [
        '公开研究接口可能延迟、缺项或变更；未验证商业分发与长期保存授权',
        '按访问时效后台补齐公司概况、财务摘要与公告标题；未抓取公告正文或接入综合新闻',
        '财务为报表期内累计口径、币种人民币元；不代表单季度收入或利润',
        '披露日期与本机首次获知时间分别保存；日期级披露不证明盘中可获得',
        '资料进入Agent前按首次获知时点过滤并冻结证据；资料本身不代表正负面结论或下单许可',
        '资料缺失、目录为空或同步失败，均不能解释为公司没有风险',
    ]

    ttl = {'company': 7 * 86400, 'financials': 6 * 3600, 'announcements': 15 * 60}

    def __init__(self, store, auto_enabled=lambda: False):
        from backend.research_provider import EastmoneyResearchProvider
        self.store = store
        self.provider_factory = EastmoneyResearchProvider
        self.lock = threading.Lock()
        self.auto_enabled = auto_enabled
        self.queue_lock = threading.Lock()
        self.pending = set()
        self.active = None
        self.wakeup = threading.Event()
        self.stopping = threading.Event()
        self.thread = None

    def due_sections(self, security_id):
        """同步记录决定刷新时效；证据首次获知时间不因重复抓取而改变。"""
        current = datetime.now(timezone.utc)
        runs = [r for r in reversed(self.store.all('research_sync_run')) if r['security_id'] == security_id]
        due = []
        for section in SECTIONS:
            pointer = self.store.get('research_current', security_id + ':' + section, False)
            saved = self.store.get('research_snapshot', pointer['snapshot_id'], False) if pointer else None
            needs_upgrade = section == 'financials' and (saved or {}).get('data', {}).get('schema_version', 1) < getattr(self.provider_factory, 'financial_schema_version', 1)
            latest = next((r for r in runs if section in r.get('requested_sections', [])
                           or section in r['updated_sections']
                           or any(e.startswith(LABELS[section] + '：') for e in r['errors'])), None)
            finished = self._time(latest.get('finished_at')) if latest else None
            if finished:
                age = (current - finished).total_seconds()
                if age < (self.ttl[section] if section in latest['updated_sections'] else 900) and (section not in latest['updated_sections'] or not needs_upgrade):
                    continue
            received = self._time(saved.get('received_at')) if saved else None
            if not latest and received and (current - received).total_seconds() < self.ttl[section] and not needs_upgrade:
                continue
            due.append(section)
        # 分红缓存独立计时；不能因其他栏目新鲜而永远不进行首次补齐。
        if callable(getattr(self.provider_factory, 'corporate_actions', None)):
            actions = self.store.get('stock_corporate_actions', security_id, False) or {}
            checked = self._time(actions.get('checked_at'))
            if not checked or (current - checked).total_seconds() >= (900 if actions.get('error') else 86400):
                latest = next((r for r in runs if 'announcements' in r.get('requested_sections', [])), None)
                failed_at = self._time(latest.get('finished_at')) if latest and 'announcements' not in latest['updated_sections'] else None
                if (not failed_at or (current-failed_at).total_seconds() >= 900) and 'announcements' not in due:
                    due.append('announcements')
        return due

    def request_auto(self, security_id):
        if (not security_id.startswith('LIVE.') or not self.supported(security_id)
                or not self.auto_enabled() or self.stopping.is_set()):
            return
        if not self.due_sections(security_id):
            return
        with self.queue_lock:
            if security_id != self.active and len(self.pending) < 20:
                self.pending.add(security_id)
        self.wakeup.set()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, name='stock-research-cache', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _loop(self):
        while not self.stopping.is_set():
            self.wakeup.wait(30)
            self.wakeup.clear()
            while not self.stopping.is_set():
                with self.queue_lock:
                    if not self.pending:
                        break
                    key = self.pending.pop()
                    self.active = key
                try:
                    sections = self.due_sections(key)
                    if self.auto_enabled() and sections:
                        self.sync(key, sections, automatic=True)
                except ProviderError as exc:
                    if exc.code == 'RESEARCH_BUSY':
                        # 手动同步占用时稍后再检查，不将互斥错误记为来源失败。
                        with self.queue_lock:
                            self.pending.add(key)
                        break
                finally:
                    with self.queue_lock:
                        self.active = None

    def runs(self, security_id=None):
        return [r for r in reversed(self.store.all('research_sync_run'))
                if security_id is None or r['security_id'] == security_id][:30]

    def supported(self, security_id):
        try:
            canonical(security_id)
            return True
        except ProviderError:
            return False

    def provider(self):
        runs = self.runs()
        latest = runs[0] if runs else None
        return dict(id=self.provider_id, name='东方财富公司、财务与公告目录', data_mode='RESEARCH',
            status=self._status(latest), connected=bool(self.store.all('research_current')),
            source='东方财富固定HTTPS研究端点 / 本地缓存',
            last_updated_at=latest['finished_at'] if latest else None,
            error='；'.join(latest['errors']) if latest and latest['errors'] else None,
            capabilities=['公司概况', '最近4期财务摘要', '最近10条公告标题', '首次获知与版本证据'],
            limitations=self.limitations)

    @staticmethod
    def _status(run):
        return 'AVAILABLE' if not run else {'SUCCEEDED': 'SYNCED', 'PARTIAL': 'PARTIAL'}.get(run['status'], 'ERROR')

    def profile(self, security_id):
        original = self.store.get('profile', security_id, False)
        base = deepcopy(original) if original else dict(security_id=security_id, business=None, facts=[], events=[], limitations=[])
        base.pop('id', None)
        base['financials'], base['evidence'] = [], []
        actions = self.store.get('stock_corporate_actions', security_id, False)
        base['corporate_actions'] = {k:v for k,v in actions.items() if k != 'id'} if actions else None
        available_sections = []
        saved_sections = {}
        for section in SECTIONS:
            current = self.store.get('research_current', security_id + ':' + section, False)
            saved = self.store.get('research_snapshot', current['snapshot_id'], False) if current else None
            if not saved:
                continue
            saved_sections[section] = saved
            available_sections.append(section)
            evidence = {k: saved[k] for k in ('id', 'section', 'source', 'source_url', 'received_at', 'available_at', 'raw_hash')}
            base['evidence'].append(evidence)
            if section == 'company':
                base['business'] = saved['data']['business']
                base['facts'] = saved['data']['facts']
            elif section == 'financials':
                base['financials'] = saved['data']['records']
            else:
                base['events'] = saved['data']['events']
        runs = self.runs(security_id)
        latest = runs[0] if runs else None
        section_status = {
            section: dict(
                status='SYNCED' if section in saved_sections else 'AVAILABLE',
                last_attempt_at=None,
                last_updated_at=saved_sections.get(section, {}).get('received_at'),
                source=saved_sections.get(section, {}).get('source'),
                error=None,
            )
            for section in SECTIONS
        }
        for run in runs:
            for section in SECTIONS:
                current_status = section_status[section]
                if current_status['last_attempt_at'] is not None:
                    continue
                error = next((message for message in run['errors']
                              if message.startswith(LABELS[section] + '：')), None)
                if section in run['updated_sections']:
                    current_status.update(status='SYNCED', last_attempt_at=run['finished_at'], error=None)
                elif error or section in run.get('requested_sections', []):
                    current_status.update(
                        status='STALE' if section in saved_sections else 'ERROR',
                        last_attempt_at=run['finished_at'],
                        error=error.split('：', 1)[-1] if error else '研究来源初始化失败，保留已有数据',
                    )
        with self.queue_lock:
            pending = security_id in self.pending or security_id == self.active
        base['research'] = dict(supported=self.supported(security_id), provider_id=self.provider_id,
            status=self._status(latest), last_synced_at=latest['finished_at'] if latest else None,
            error='；'.join(latest['errors']) if latest and latest['errors'] else None,
            sections=available_sections, section_status=section_status, limitations=self.limitations,
            auto_refresh=dict(enabled=bool(self.auto_enabled()), pending=pending))
        if not available_sections and not original:
            base['limitations'] = ['尚未保存公司资料；自动更新开启时后台补齐，无资料不表示无风险。']
        base['limitations'] = list(dict.fromkeys(base['limitations'] + self.limitations))
        return base

    @staticmethod
    def _time(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
        except (TypeError, ValueError, OverflowError):
            return None

    def agent_context(self, security_id, as_of):
        """按信号确认时点筛选研究资料，并保留完整证据清单供复核审计。"""
        cutoff = self._time(as_of)
        manifest = []
        context = dict(as_of=as_of, evidence=manifest, company=None, financials=[], announcements=[])
        # 在同一读锁内固定版本，避免同步线程在读取不同分节时切换指针。
        with self.store.lock:
            snapshots = [item for item in self.store.all('research_snapshot')
                         if item.get('security_id') == security_id]
            for section in SECTIONS:
                candidates = [item for item in snapshots if item.get('section') == section]
                known = [item for item in candidates if cutoff and self._time(item.get('available_at'))
                         and self._time(item['available_at']) <= cutoff]
                pointer = self.store.get('research_current', security_id + ':' + section, False)
                current = next((item for item in candidates if pointer and item['id'] == pointer['snapshot_id']), None)
                chosen = max(known, key=lambda item: (self._time(item['available_at']),
                    item['id'] == (current or {}).get('id'), item['id'])) if known else None
                for saved, included in [(chosen, True), (current, False)]:
                    if not saved or (not included and chosen and saved['id'] == chosen['id']):
                        continue
                    row = {key: saved.get(key) for key in
                           ('id', 'section', 'source', 'source_url', 'available_at', 'received_at', 'raw_hash')}
                    available = self._time(saved.get('available_at'))
                    reason = ('资料首次获知时间晚于信号确认时刻，避免未来信息'
                              if cutoff and available else '缺少可比较的获知时间')
                    row.update(included=included, exclusion_reason=None if included else reason)
                    manifest.append(row)
                if chosen:
                    data = deepcopy(chosen['data'])
                    if section == 'company':
                        context['company'] = data
                    elif section == 'financials':
                        context['financials'] = data['records']
                    else:
                        context['announcements'] = data['events']
        return context

    def revision_hash(self, security_id, as_of):
        """绑定当前分节版本；同步相同版本不失效，新资料或修订须显式重新复核。"""
        with self.store.lock:
            revisions = []
            for section in SECTIONS:
                pointer = self.store.get('research_current', security_id + ':' + section, False)
                revisions.append([section, pointer['snapshot_id'] if pointer else None])
        return digest([security_id, as_of, revisions])

    def _save(self, security_id, section, response):
        if response.get('security_id') != canonical(security_id):
            raise ProviderError('IDENTITY_MISMATCH', '研究资料证券身份不一致，未保存')
        for key in ('source', 'source_url', 'received_at', 'raw_hash'):
            if not isinstance(response.get(key), str) or not response[key]:
                raise ProviderError('INVALID_EVIDENCE', '研究资料缺少来源证据，未保存')
        payload = {key: deepcopy(response[key]) for key in
                   (('business', 'facts') if section == 'company' else ('records',) if section == 'financials' else ('events',))}
        if section == 'financials' and 'schema_version' in response:
            payload['schema_version'] = response['schema_version']
        received = response['received_at']
        with self.store.lock, self.store.db:
            # 每条修订首次获知时间稳定；新披露/修订内容产生独立证据。
            records = payload.get('records', payload.get('events', []))
            for record in records:
                identity = digest([security_id, section, record])
                observed = self.store.get('research_observation', identity, False)
                available = observed['available_at'] if observed else received
                if not observed:
                    self.store.put('research_observation', dict(id=identity, available_at=available))
                record.update(source=response['source'], received_at=received, available_at=available, raw_hash=response['raw_hash'])
                if section == 'announcements':
                    record['summary'] = '仅同步公告标题与目录元数据，尚未读取原文，不构成正负面结论。'
            identity = [security_id, section, response['raw_hash']]
            if 'schema_version' in payload:
                identity.append(payload['schema_version'])
            snapshot_id = digest(identity)
            saved = self.store.get('research_snapshot', snapshot_id, False)
            if not saved:
                saved = dict(id=snapshot_id, security_id=security_id, section=section, source=response['source'],
                    source_url=response['source_url'], received_at=received, available_at=received,
                    raw_hash=response['raw_hash'], data=payload)
                self.store.put('research_snapshot', saved)
            self.store.put('research_current', dict(id=security_id + ':' + section, snapshot_id=snapshot_id))

    def sync(self, security_id, sections=None, *, automatic=False):
        sid = canonical(security_id)
        chosen = list(SECTIONS) if sections is None else sections
        if not isinstance(chosen, list) or not chosen or len(chosen) > 3 or any(not isinstance(x, str) or x not in SECTIONS for x in chosen) or len(set(chosen)) != len(chosen):
            raise ProviderError('INVALID_SECTIONS', '请选择不重复的公司概况、财务摘要或公告目录')
        if not self.lock.acquire(blocking=False):
            raise ProviderError('RESEARCH_BUSY', '已有研究资料同步运行中，请稍后重试')
        run = dict(id=uuid.uuid4().hex, security_id=security_id, provider_id=self.provider_id,
            status='FAILED', started_at=now(), finished_at=None, requested_sections=list(chosen),
            updated_sections=[], errors=[], limitations=self.limitations)
        client = None
        try:
            client = self.provider_factory()
            for section in chosen:
                if automatic and (self.stopping.is_set() or not self.auto_enabled()):
                    run['errors'].append(LABELS[section] + '：自动更新已暂停，保留已有数据')
                    continue
                try:
                    self._save(security_id, section, getattr(client, section)(sid))
                    run['updated_sections'].append(section)
                except ProviderError as exc:
                    run['errors'].append(LABELS[section] + '：' + exc.message)
                except Exception:
                    run['errors'].append(LABELS[section] + '：处理失败，保留原有缓存')
            # 企业行为仅作页面事实展示，独立缓存，不混入Agent冻结证据或策略输入。
            if hasattr(client, 'corporate_actions'):
                old = self.store.get('stock_corporate_actions', security_id, False)
                checked = self._time((old or {}).get('checked_at'))
                due = not checked or (datetime.now(timezone.utc)-checked).total_seconds() >= (900 if (old or {}).get('error') else 86400)
                if (not automatic or due) and (not automatic or not self.stopping.is_set() and self.auto_enabled()):
                    try:
                        actions = client.corporate_actions(sid)
                        if actions.get('security_id') != sid:
                            raise ProviderError('IDENTITY_MISMATCH', '分红与除权证券身份不匹配')
                        saved = dict(**actions, id=security_id, checked_at=now(), error=None)
                    except Exception:
                        saved = {**(old or {}), 'id':security_id, 'checked_at':now(),
                                 'error':'分红与除权来源暂不可用，保留已有数据'}
                    with self.store.lock, self.store.db:
                        self.store.put('stock_corporate_actions', saved)
        except Exception:
            run['errors'].append('研究来源初始化失败，保留已有数据')
        finally:
            if client:
                try:
                    client.close()
                except Exception:
                    pass
            try:
                run['status'] = ('PARTIAL' if run['updated_sections'] else 'FAILED') if run['errors'] else 'SUCCEEDED'
                run['finished_at'] = now()
                with self.store.lock, self.store.db:
                    self.store.put('research_sync_run', run)
            finally:
                self.lock.release()
        return run

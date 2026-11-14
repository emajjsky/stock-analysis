<script setup lang="ts">
import { ref, onMounted, watch } from "vue";
import { Plus, ArrowRight, ShieldAlert, CalendarPlus } from "lucide-vue-next";
import { state, action, inform } from "../state";
import { api, post } from "../api";
import type { Account, AccountDetail, Order } from "../types";
import { money, label, direction, date } from "../format";
import EmptyState from "../components/EmptyState.vue";
const section = ref("SIM"),
  accounts = ref<Account[]>([]),
  selected = ref(""),
  detail = ref<AccountDetail>(),
  name = ref(""),
  cash = ref(""),
  mode = ref("DEMO"),
  security = ref(""),
  side = ref("BUY"),
  quantity = ref(100),
  purpose = ref("BASE"),
  busy = ref(false),
  live = ref<{ enabled: false; status: string; requirements: string[] }>(),
  pendingKey = ref("");
watch(
  [selected, security, side, quantity, purpose],
  () => (pendingKey.value = ""),
);
async function load() {
  const r = await action(() => api<Account[]>("/sim/accounts"));
  if (r) accounts.value = r.data;
  if (selected.value) await loadDetail();
  const l = await action(() =>
    api<{ enabled: false; status: string; requirements: string[] }>(
      "/live/status",
    ),
  );
  if (l) live.value = l.data;
}
async function loadDetail() {
  detail.value = undefined;
  if (!selected.value) return;
  const id = selected.value;
  const r = await action(() => api<AccountDetail>(`/sim/accounts/${id}`));
  if (r && id === selected.value) detail.value = r.data;
}
onMounted(load);
async function create() {
  if (!name.value.trim() || !cash.value || Number(cash.value) <= 0) {
    inform("请填写账户名称和大于零的初始资金");
    return;
  }
  busy.value = true;
  const r = await action(
    () =>
      post<Account>("/sim/accounts", {
        name: name.value.trim(),
        initial_cash: String(cash.value),
        mode: mode.value,
      }),
    "模拟账户已建立，尚未启用自动交易",
  );
  if (r) {
    selected.value = r.data.id;
    cash.value = "";
    name.value = "";
    await load();
  }
  busy.value = false;
}
async function order() {
  if (!selected.value || !security.value || quantity.value <= 0) return;
  if (
    !confirm(
      `确认提交${side.value === "BUY" ? "买入" : "卖出"} ${quantity.value} 股模拟委托？使用当前账户日期的已保存行情撮合，不是真实盘中成交。`,
    )
  )
    return;
  pendingKey.value ||= crypto.randomUUID();
  busy.value = true;
  const r = await action(() =>
    post<Order>(`/sim/accounts/${selected.value}/orders`, {
      security_id: security.value,
      side: side.value,
      quantity: quantity.value,
      purpose: purpose.value,
      idempotency_key: pendingKey.value,
    }),
  );
  if (r) {
    pendingKey.value = "";
    inform(
      r.data.status === "REJECTED"
        ? `委托已拒绝：${r.data.reject_reason ?? "请查看订单记录"}`
        : "模拟委托已处理，请检查订单状态",
    );
    await load();
  } else {
    await loadDetail();
  }
  busy.value = false;
}
async function advance() {
  busy.value = true;
  const r = await action(
    () => post(`/sim/accounts/${selected.value}/advance-day`),
    "已推进到演示数据的下一交易日",
  );
  if (r) {
    pendingKey.value = "";
    await load();
  }
  busy.value = false;
}
</script>
<template>
  <section class="page-heading">
    <div>
      <div class="eyebrow">TRADING / 10 · 11</div>
      <h1>交易实验室</h1>
      <p>从独立账户开始，区分信号、委托和实际结果。</p>
    </div>
    <span class="badge blue">交易入口 · 与看盘独立</span>
  </section>
  <div class="tabs bottom-gap">
    <button :class="{ active: section === 'SIM' }" @click="section = 'SIM'">
      模拟交易</button
    ><button :class="{ active: section === 'LIVE' }" @click="section = 'LIVE'">
      真实交易 <span class="tiny">未开放</span>
    </button>
  </div>
  <template v-if="section === 'LIVE'"
    ><section class="panel inset">
      <ShieldAlert :size="32" />
      <h2>实盘连接尚未开放</h2>
      <p>没有配置券商凭据，也没有实盘下单接口。此处无法提交任何真实委托。</p>
      <ul>
        <li v-for="r in live?.requirements">{{ r }}</li>
      </ul>
      <button class="button" disabled>连接实盘账户（未开放）</button>
    </section></template
  ><template v-else
    ><div class="trading-layout">
      <aside class="panel inset">
        <h2>模拟账户</h2>
        <label class="field"
          >选择账户<select v-model="selected" @change="loadDetail">
            <option value="">选择或创建账户</option>
            <option v-for="a in accounts" :value="a.id">
              {{ a.name }} · {{ label(a.mode) }}
            </option>
          </select></label
        >
        <div class="divider top-gap">
          <h3>新建独立实验</h3>
          <label class="field"
            >账户名称<input
              v-model="name"
              placeholder="例如：波段基线实验"
              maxlength="60" /></label
          ><label class="field"
            >初始资金（人民币）<input
              v-model="cash"
              type="number"
              min="0.01"
              step="0.01"
              placeholder="由你设定，不预填资金" /></label
          ><label class="field"
            >行情环境<select v-model="mode">
              <option value="DEMO">合成演示数据</option>
              <option value="IMPORTED">历史导入数据</option>
            </select></label
          ><button class="button full" :disabled="busy" @click="create">
            <Plus :size="14" />创建模拟账户
          </button>
          <p class="tiny muted">
            创建后固定初始资金。账户不会自动交易。演示与导入数据不可混作实盘结果。
          </p>
        </div>
      </aside>
      <div v-if="detail" class="trading-main">
        <div class="environment-strip">
          <strong>模拟 · {{ label(detail.account.mode) }}</strong
          ><span
            >{{ detail.account.name }} / {{ detail.account.trade_date }}</span
          ><button
            class="button small"
            @click="advance"
            :disabled="busy || detail.account.mode !== 'DEMO'"
            title="仅演示数据可推进到已有下一交易日"
          >
            <CalendarPlus :size="13" />推进演示交易日
          </button>
        </div>
        <section class="panel metric-grid inset">
          <div>
            <small>账户总权益</small
            ><strong>{{ money(detail.account.equity) }}</strong>
          </div>
          <div>
            <small>可用现金</small
            ><strong>{{ money(detail.account.cash) }}</strong>
          </div>
          <div>
            <small>持仓市值</small
            ><strong>{{ money(detail.account.market_value) }}</strong>
          </div>
          <div>
            <small>累计盈亏</small
            ><strong :class="direction(detail.account.total_pnl)">{{
              money(detail.account.total_pnl)
            }}</strong>
          </div>
        </section>
        <section class="panel inset">
          <div class="section-label">
            <h2>手工模拟委托</h2>
            <span class="tiny muted">保存价撮合 · 非盘中成交</span>
          </div>
          <form class="order-form" @submit.prevent="order">
            <label class="field"
              >证券<select v-model="security" required>
                <option value="">请选择</option>
                <option v-for="s in state.securities" :value="s.id">
                  {{ s.name }} {{ s.code }}
                </option>
              </select></label
            ><label class="field"
              >方向<select v-model="side" @change="pendingKey = ''">
                <option value="BUY">买入</option>
                <option value="SELL">卖出</option>
              </select></label
            ><label class="field"
              >数量（股）<input
                v-model.number="quantity"
                type="number"
                min="1"
                step="1"
                required
                @input="pendingKey = ''" /></label
            ><label class="field"
              >操作归因<select v-model="purpose" @change="pendingKey = ''">
                <option value="BASE">基础持仓操作</option>
                <option value="T">做 T 操作</option>
              </select></label
            ><button class="button primary" :disabled="busy || !security">
              提交模拟委托
            </button>
          </form>
          <p class="tiny muted">
            T+1：今日买入不增加当日可卖库存。超时重试保留同一幂等键，成交与否以订单记录为准。自动执行方案与自动做
            T
            尚未开放。导入数据复权方式未知时禁止模拟成交，请使用明确未复权的数据集。
          </p>
        </section>
        <section class="panel">
          <div class="inset section-label"><h2>当前持仓</h2></div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>证券</th>
                  <th class="numeric">持有 / 可卖</th>
                  <th class="numeric">今日买入</th>
                  <th class="numeric">平均成本</th>
                  <th class="numeric">持仓市值</th>
                  <th class="numeric">未实现盈亏</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in detail.positions">
                  <td>
                    {{ p.security.name }}<small>{{ p.security.code }}</small>
                  </td>
                  <td class="numeric">{{ p.quantity }} / {{ p.sellable }}</td>
                  <td class="numeric">{{ p.today_bought }}</td>
                  <td class="numeric">{{ money(p.average_cost) }}</td>
                  <td class="numeric">{{ money(p.market_value) }}</td>
                  <td class="numeric" :class="direction(p.unrealized_pnl)">
                    {{ money(p.unrealized_pnl) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!detail.positions.length" class="inset muted">暂无持仓。</p>
        </section>
        <section class="panel inset">
          <div class="section-label">
            <h2>做 T 与不做 T 对照</h2>
            <span class="badge">{{ label(detail.comparison.status) }}</span>
          </div>
          <div class="metric-grid">
            <div>
              <small>实际操作权益</small
              ><strong>{{ money(detail.comparison.actual_equity) }}</strong>
            </div>
            <div>
              <small>不做 T 对照权益</small
              ><strong>{{ money(detail.comparison.baseline_equity) }}</strong>
            </div>
            <div>
              <small>做 T 净增益</small
              ><strong :class="direction(detail.comparison.t_increment)">{{
                detail.comparison.status === "COMPARABLE"
                  ? money(detail.comparison.t_increment)
                  : "不可比"
              }}</strong>
            </div>
          </div>
          <div class="metric-grid top-gap">
            <div>
              <small>今日实际盈亏</small
              ><strong>{{ money(detail.comparison.today_actual_pnl) }}</strong>
            </div>
            <div>
              <small>今日不做 T 盈亏</small
              ><strong>{{
                money(detail.comparison.today_baseline_pnl)
              }}</strong>
            </div>
            <div>
              <small>今日 T 净增益</small
              ><strong>{{
                detail.comparison.status === "COMPARABLE"
                  ? money(detail.comparison.today_t_increment)
                  : "不可比"
              }}</strong>
            </div>
          </div>
          <p>{{ detail.comparison.explanation }}</p>
          <p class="tiny muted">
            费用 {{ money(detail.comparison.fees) }} · 未完成 T 数量
            {{ detail.comparison.open_t_quantity }} 股。T
            增益已包含在账户总权益中，不重复相加。
          </p>
        </section>
        <section class="panel">
          <div class="inset section-label"><h2>委托与处理记录</h2></div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>证券 / 时间</th>
                  <th>方向 / 归因</th>
                  <th class="numeric">数量 / 成交</th>
                  <th class="numeric">价格</th>
                  <th class="numeric">费用</th>
                  <th>状态与原因</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="o in detail.orders" :key="o.id">
                  <td>
                    {{
                      state.securities.find((s) => s.id === o.security_id)
                        ?.name ?? o.security_id
                    }}<small>{{ date(o.created_at) }}</small>
                  </td>
                  <td>
                    {{ o.side === "BUY" ? "买入" : "卖出" }} /
                    {{ o.purpose === "T" ? "做T" : "基础" }}
                  </td>
                  <td class="numeric">
                    {{ o.quantity }} / {{ o.filled_quantity }}
                  </td>
                  <td class="numeric">{{ money(o.price) }}</td>
                  <td class="numeric">{{ money(o.fee) }}</td>
                  <td>
                    {{ label(o.status) }}<small>{{ o.reject_reason }}</small>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!detail.orders.length" class="inset muted">尚无委托。</p>
        </section>
      </div>
      <EmptyState
        v-else
        title="为每次实验建立独立账户"
        description="在左侧输入你希望使用的资金，建立模拟实验。看盘、选股与信号功能无需创建账户。"
      /></div
  ></template>
</template>

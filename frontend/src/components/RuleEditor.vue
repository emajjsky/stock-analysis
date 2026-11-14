<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { X, Save } from "lucide-vue-next";
import { state, action, refresh } from "../state";
import { post } from "../api";
import { label } from "../format";
const props = defineProps<{ securityId?: string }>();
defineEmits<{ close: [] }>();
const security = ref(props.securityId ?? state.securities[0]?.id ?? ""),
  algorithm = ref(
    state.algorithms.find((a) => a.kind !== "SELECTION")?.id ?? "",
  ),
  enabled = ref(true),
  agent = ref("EXPLAIN"),
  parameters = ref<Record<string, string>>({}),
  saving = ref(false);
const selected = computed(() =>
  state.algorithms.find((a) => a.id === algorithm.value),
);
watch(
  [security, algorithm],
  () => {
    const m = state.monitors.find(
      (m) =>
        m.security_id === security.value && m.algorithm_id === algorithm.value,
    );
    enabled.value = m?.enabled ?? true;
    agent.value = m?.agent_mode ?? "EXPLAIN";
    parameters.value = Object.fromEntries(
      Object.entries(m?.parameters ?? selected.value?.parameters ?? {}).map(
        ([k, v]) => [k, String(v)],
      ),
    );
  },
  { immediate: true },
);
async function save() {
  if (!security.value || !algorithm.value) return;
  const values: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(parameters.value)) {
    if (v.trim() !== "" && Number.isFinite(Number(v))) values[k] = Number(v);
    else values[k] = v;
  }
  saving.value = true;
  const r = await action(
    () =>
      post("/monitors", {
        security_id: security.value,
        algorithm_id: algorithm.value,
        enabled: enabled.value,
        parameters: values,
        agent_mode: agent.value,
      }),
    "监测配置已保存；不会自动下单",
  );
  if (r) await refresh();
  saving.value = false;
}
</script>
<template>
  <div class="modal-scrim" @click.self="$emit('close')">
    <section
      class="drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="rule-title"
    >
      <header class="drawer-header">
        <div>
          <div class="eyebrow">ALGORITHM / 07</div>
          <h2 id="rule-title">算法与监测规则</h2>
        </div>
        <button class="icon-button" aria-label="关闭" @click="$emit('close')">
          <X />
        </button>
      </header>
      <div class="drawer-content">
        <label class="field"
          >监测对象<select v-model="security">
            <option disabled value="">请先导入证券</option>
            <option v-for="s in state.securities" :value="s.id">
              {{ s.name }} · {{ s.code }}
            </option>
          </select></label
        ><label class="field"
          >算法模板<select v-model="algorithm">
            <option
              v-for="a in state.algorithms.filter(
                (a) => a.kind !== 'SELECTION',
              )"
              :value="a.id"
            >
              {{ a.name }} · {{ a.version }}
            </option>
          </select></label
        >
        <div v-if="selected" class="subtle">
          <div class="flex spread">
            <strong>{{ selected.name }}</strong
            ><span class="badge">{{ label(selected.status) }}</span>
          </div>
          <p>{{ selected.description }}</p>
          <p class="tiny muted">
            周期 {{ selected.timeframe }} · {{ selected.version }}
          </p>
          <ul class="tiny">
            <li v-for="l in selected.limitations">{{ l }}</li>
          </ul>
        </div>
        <p class="tiny muted">
          选股模板用于发现候选；这里仅配置 SIGNAL / T 类监测模板。
        </p>
        <h3 class="top-gap">模板参数</h3>
        <p class="tiny muted">
          使用服务端模板支持的参数，保存时由服务端校验。任意公式和复杂条件编辑器尚未开放。
        </p>
        <label v-for="(_, key) in parameters" class="field"
          >{{ key }}<input v-model="parameters[key]" required
        /></label>
        <p v-if="!Object.keys(parameters).length" class="muted">
          该模板暂无可调整参数。
        </p>
        <label class="field"
          >Agent 工作方式<select v-model="agent">
            <option value="OFF">关闭 · 只保留算法判断</option>
            <option value="EXPLAIN">仅解释 · 不改变算法信号</option>
            <option value="FILTER">参与过滤 · 不支持或不可用时不放行</option>
          </select></label
        >
        <div class="subtle" v-if="!state.settings?.agent_configured">
          当前未配置 LLM。请求复核将返回“等待 /
          未配置”，不会默认支持。规则演示需要单独显式触发，不能当作 AI。
        </div>
        <label class="check-row top-gap"
          ><input type="checkbox" v-model="enabled" />启用该算法的监测</label
        >
        <h3 class="top-gap">执行边界</h3>
        <p class="muted">
          这里保存监测与提示规则。定时检查请到自选页开启“自动监测”，只使用已保存行情。
          自动模拟、做 T 自动执行和实盘授权尚未开放；模拟手工委托请从独立交易入口进入。
        </p>
        <div class="subtle">
          信号仅使用已完成行情；支持条件满足后确认，不回移到历史低点。参数修改不意味着历史结果已重新验证。
        </div>
        <h3 class="top-gap">已有监测</h3>
        <div v-for="m in state.monitors" class="compact-row">
          <span>{{
            state.securities.find((s) => s.id === m.security_id)?.name ??
            m.security_id
          }}</span
          ><span>{{
            state.algorithms.find((a) => a.id === m.algorithm_id)?.name ??
            m.algorithm_id
          }}</span
          ><span class="badge"
            >{{ label(m.agent_mode) }} · {{ m.enabled ? "启用" : "暂停" }}</span
          >
        </div>
      </div>
      <footer class="drawer-footer">
        <button class="button" @click="$emit('close')">关闭</button
        ><button
          class="button primary"
          :disabled="saving || !security || !algorithm"
          @click="save"
        >
          <Save :size="15" />{{ saving ? "保存中…" : "保存监测规则" }}
        </button>
      </footer>
    </section>
  </div>
</template>

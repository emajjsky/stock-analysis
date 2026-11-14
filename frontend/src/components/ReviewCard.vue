<script setup lang="ts">
import { computed } from "vue";
import type { Review } from "../types";
import { label, date } from "../format";
import { researchTime, sectionName } from "../research";
import {
  bindingPresentation,
  evidenceReason,
  modelRequestLabel,
  reviewErrorLabel,
  reviewManifest,
  safeResearchUrl,
} from "../reviewEvidence";

const props = defineProps<{ review: Review | null | undefined }>();
const manifest = computed(() =>
  props.review ? reviewManifest(props.review) : [],
);
const includedCount = computed(
  () => manifest.value.filter((item) => item.included).length,
);
const binding = computed(() =>
  props.review ? bindingPresentation(props.review) : null,
);
const cited = (id: string) =>
  props.review?.cited_evidence_ids?.includes(id) ?? false;
</script>
<template>
  <div v-if="review" class="review-card">
    <div class="flex spread">
      <span class="badge blue">{{ label(review.verdict) }}</span
      ><span class="muted tiny">{{
        review.mode === "RULE_DEMO"
          ? "规则演示 · 非 AI"
          : review.mode === "UNAVAILABLE"
            ? "模型结果不可用"
            : "模型复核"
      }}</span>
    </div>
    <p v-if="binding?.requiresReview" class="binding-warning" role="status">
      {{ binding.label }}：旧立场只供历史查看，请重新复核。
    </p>
    <h3>{{ review.summary }}</h3>
    <template
      v-for="[name, items] of [
        ['支持证据', review.supporting_evidence],
        ['反对证据', review.opposing_evidence],
        ['未知信息', review.unknowns],
        ['附加条件', review.conditions],
        ['局限', review.limitations],
      ]"
      :key="String(name)"
      ><div v-if="(items as string[]).length" class="evidence">
        <strong>{{ name }}</strong>
        <ul>
          <li v-for="item in items as string[]" :key="item">{{ item }}</li>
        </ul>
      </div></template
    >
    <p class="tiny muted">
      {{ review.model }} · {{ date(review.created_at) }}<br />有效至
      {{ date(review.valid_until) }}
    </p>
    <p class="tiny muted research-model-note">
      {{ modelRequestLabel(review) }}
    </p>
    <p v-if="review.model_error_code" class="tiny binding-warning" role="status">
      {{ reviewErrorLabel(review.model_error_code) }}；本次结论保持等待。
    </p>
    <p v-if="review.model_latency_ms != null" class="tiny muted">
      模型请求耗时 {{ review.model_latency_ms }} 毫秒
    </p>
    <section class="research-binding" aria-label="Agent 研究证据绑定">
      <div class="flex spread wrap">
        <strong>研究证据绑定</strong>
        <span class="badge" :class="'binding-' + binding?.status">{{
          binding?.label
        }}</span>
      </div>
      <p v-if="review.research_context_snapshot?.as_of" class="tiny muted">
        上下文截至 {{ researchTime(review.research_context_snapshot.as_of) }}
      </p>
      <details v-if="review.research_revision_hash" class="research-revision">
        <summary>查看绑定修订哈希</summary>
        <small>{{ review.research_revision_hash }}</small>
      </details>
      <template v-if="manifest.length">
        <p class="tiny muted">
          共 {{ manifest.length }} 条资料：纳入 {{ includedCount }}，排除
          {{ manifest.length - includedCount }}。各项排除原因按后端记录展示。
        </p>
        <details
          v-for="(item, index) in manifest"
          :key="item.id + ':' + item.raw_hash + ':' + index"
          class="research-evidence-item"
        >
          <summary>
            <span>{{ sectionName(item.section) }} · {{ item.source }}</span>
            <span
              class="evidence-state"
              :class="{ excluded: !item.included }"
              >{{ item.included ? "已纳入" : "已排除" }}</span
            >
            <span v-if="cited(item.id)" class="evidence-cited"
              >已引用（后端已校验）</span
            >
          </summary>
          <div class="research-evidence-detail">
            <p>{{ evidenceReason(item) }}</p>
            <small>首次可获知：{{ researchTime(item.available_at) }}</small>
            <small>实际接收：{{ researchTime(item.received_at) }}</small>
            <small>原始哈希：{{ item.raw_hash || "未提供" }}</small>
            <small>证据编号：{{ item.id }}</small>
            <a
              v-if="safeResearchUrl(item.source_url)"
              :href="safeResearchUrl(item.source_url)!"
              target="_blank"
              rel="noopener noreferrer"
              >查看东方财富来源</a
            >
            <small v-else>无可用的 HTTPS 东方财富来源链接。</small>
          </div>
        </details>
      </template>
      <p v-else class="tiny muted research-empty">
        本条复核没有研究资料记录。旧后端或未保存研究资料时，不能推断模型已经消费相关资料。
      </p>
    </section>
  </div>
  <div v-else class="subtle">
    <strong>尚未复核</strong>
    <p>算法信号独立保存；Agent 的意见不会改写原始信号。</p>
  </div>
</template>

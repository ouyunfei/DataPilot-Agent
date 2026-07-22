<template>
  <div class="overview-page" v-loading="loading">
    <el-alert v-if="requestError" :title="requestError" type="error" show-icon class="page-alert" />

    <div class="stats-grid">
      <StatCard label="总查询数" :value="stats?.total_queries ?? 0" hint="累计问数请求" />
      <StatCard label="成功率" :value="successRate" hint="成功查询 / 总查询" />
      <StatCard label="失败数" :value="stats?.failed_queries ?? 0" hint="被拦截或执行失败" />
      <StatCard label="可信答案命中" :value="stats?.trusted_answer_queries ?? 0" hint="高频问题直接命中" />
      <StatCard label="平均耗时" :value="`${Math.round(stats?.average_duration_ms || 0)}ms`" hint="端到端查询耗时" />
    </div>

    <div class="overview-grid">
      <ChartCard title="图表类型分布" :rows="chartTypeRows" :chart="{ type: 'bar', x: 'type', y: 'count', reason: '统计 Agent 推荐图表类型分布。' }" />
      <ChartCard title="反馈分布" :rows="feedbackRows" :chart="{ type: 'pie', x: 'type', y: 'count', reason: '统计用户点赞和点踩反馈。' }" />
    </div>

    <div class="overview-grid lower-grid">
      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="card-header-row">
            <span>高频问题</span>
            <el-button size="small" @click="loadOverview">刷新</el-button>
          </div>
        </template>
        <div v-if="stats?.top_questions.length" class="top-question-list">
          <div v-for="item in stats.top_questions" :key="item.question" class="top-question-item">
            <span>{{ item.question }}</span>
            <el-tag size="small">{{ item.count }} 次</el-tag>
          </div>
        </div>
        <el-empty v-else description="暂无高频问题" :image-size="72" />
      </el-card>

      <el-card shadow="never" class="panel-card">
        <template #header>
          <div class="card-header-row">
            <span>最近查询</span>
            <span class="muted-text">{{ logs.length }} 条</span>
          </div>
        </template>
        <el-table v-if="logs.length" :data="logs" stripe max-height="360">
          <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
          <el-table-column prop="chart_type" label="图表" width="90" />
          <el-table-column prop="row_count" label="行数" width="80" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag :type="row.error ? 'danger' : 'success'" size="small">{{ row.error ? '失败' : '成功' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="duration_ms" label="耗时(ms)" width="100" />
        </el-table>
        <el-empty v-else description="暂无查询日志" :image-size="72" />
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { getQueryLogs, getQueryStats, type QueryLogItem, type QueryStatsResponse } from '../api/client'
import ChartCard from '../components/ChartCard.vue'
import StatCard from '../components/StatCard.vue'

const stats = ref<QueryStatsResponse | null>(null)
const logs = ref<QueryLogItem[]>([])
const loading = ref(false)
const requestError = ref('')

const successRate = computed(() => {
  if (!stats.value?.total_queries) return '0%'
  return `${Math.round((stats.value.success_queries / stats.value.total_queries) * 100)}%`
})

const chartTypeRows = computed(() => toRows(stats.value?.chart_type_counts || {}))
const feedbackRows = computed(() => toRows(stats.value?.feedback_counts || {}))

function toRows(counts: Record<string, number>) {
  return Object.entries(counts).map(([type, count]) => ({ type, count }))
}

async function loadOverview() {
  loading.value = true
  requestError.value = ''
  try {
    const [statsResult, logsResult] = await Promise.all([getQueryStats(), getQueryLogs(10)])
    stats.value = statsResult
    logs.value = logsResult.items
  } catch (error) {
    requestError.value = error instanceof Error ? error.message : '加载数据概览失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadOverview)
</script>

<template>
  <div class="chatbi-page">
    <aside class="conversation-sidebar">
      <div class="conversation-head">
        <strong>智能问数</strong>
        <span class="panel-toggle">›</span>
      </div>

      <el-button class="new-chat-btn" type="primary" plain @click="newConversation">新建对话</el-button>

      <el-input v-model="search" placeholder="搜索历史问题" clearable class="history-search" />

      <div class="history-scroll">
        <section v-for="group in groupedHistory" :key="group.title" class="history-group">
          <div class="history-title">{{ group.title }}</div>
          <button
            v-for="item in group.items"
            :key="item.id"
            class="history-item"
            type="button"
            :title="item.question"
            @click="fillQuestion(item.question)"
          >
            {{ item.question }}
          </button>
        </section>

        <section v-if="!history.length" class="history-group">
          <div class="history-title">推荐问题</div>
          <button v-for="item in examples" :key="item" class="history-item" type="button" @click="fillQuestion(item)">
            {{ item }}
          </button>
        </section>
      </div>
    </aside>

    <section class="chat-stage">
      <div class="chat-scroll">
        <el-alert v-if="requestError" :title="requestError" type="error" show-icon class="page-alert" />

        <div v-if="!result" class="empty-chat-state">
          <div class="bot-mark large">DP</div>
          <h1>DataPilot 智能问数</h1>
          <p>选择一个推荐问题，或直接输入中文问题，系统会生成安全 SQL、图表和分析结论。</p>
          <div class="quick-questions">
            <button v-for="item in examples.slice(0, 3)" :key="item" type="button" @click="fillQuestion(item)">
              {{ item }}
            </button>
          </div>
        </div>

        <template v-else>
          <div class="user-bubble">
            <span>我的问题</span>
            {{ result.question }}
          </div>

          <div class="assistant-line">
            <div class="bot-mark small">DP</div>
            <el-dropdown trigger="click">
              <button class="process-btn" type="button">查看执行过程 ›</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item>召回 Schema / 指标 / 可信 SQL</el-dropdown-item>
                  <el-dropdown-item>生成并校验安全 SQL</el-dropdown-item>
                  <el-dropdown-item>执行查询并生成分析结论</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <div class="answer-card-shell">
            <ChartCard :rows="result.data" :chart="result.chart" />
            <div class="answer-toolbar">
              <button type="button" @click="fillQuestion(result.question)">继续追问</button>
              <button type="button" @click="copyAnswer">复制结论</button>
              <span>{{ timestamp }}</span>
            </div>
          </div>

          <div class="assistant-line report-line">
            <div class="bot-mark small">DP</div>
            <el-dropdown trigger="click">
              <button class="process-btn" type="button">查看 SQL 解释 ›</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item>{{ result.sql_explanation || '本次查询未返回 SQL 解释' }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <article class="report-card">
            <div class="report-head">
              <div>
                <h2>智能分析报告</h2>
                <p>基于 MySQL 示例业务库生成</p>
              </div>
              <el-tag :type="result.error ? 'danger' : 'success'" effect="plain">{{ result.error ? '查询失败' : '查询成功' }}</el-tag>
            </div>

            <el-alert
              v-if="result.error"
              :title="result.error"
              :description="result.error_code || ''"
              type="error"
              show-icon
              :closable="false"
            />
            <p v-else class="answer-text">{{ result.answer || '本次查询已完成，请查看图表与明细数据。' }}</p>

            <div v-if="result.insights.length" class="insight-list">
              <div v-for="(insight, index) in result.insights" :key="index" class="insight-item">
                <strong>{{ insight.type || 'insight' }}</strong>
                <span>{{ insight.message }}</span>
              </div>
            </div>

            <el-tabs class="result-tabs">
              <el-tab-pane label="数据表">
                <ResultTable :rows="result.data" />
              </el-tab-pane>
              <el-tab-pane label="SQL">
                <SqlCard :sql="result.sql" :explanation="result.sql_explanation" />
              </el-tab-pane>
              <el-tab-pane label="知识来源">
                <div v-if="result.knowledge_sources.length" class="knowledge-list">
                  <div v-for="source in result.knowledge_sources" :key="`${source.knowledge_type}-${source.source_id}`" class="knowledge-item">
                    <el-tag size="small" effect="plain">{{ source.knowledge_type }}</el-tag>
                    <span>{{ source.title }}</span>
                    <span class="muted-text">{{ source.score.toFixed(2) }}</span>
                  </div>
                </div>
                <el-empty v-else description="暂无知识来源" :image-size="72" />
              </el-tab-pane>
            </el-tabs>
          </article>
        </template>
      </div>

      <div class="composer-wrap">
        <div class="selected-source">当前数据源：<span>MySQL 示例业务库</span></div>
        <div class="composer">
          <el-input
            v-model="question"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入业务问题，Ctrl + Enter 发送"
            @keydown.ctrl.enter.exact.prevent="submitQuestion"
          />
          <el-button class="send-btn" type="primary" :loading="loading" @click="submitQuestion">发送</el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { askQuestion, getQueryLogs, type ChatResponse, type QueryLogItem } from '../api/client'
import ChartCard from '../components/ChartCard.vue'
import ResultTable from '../components/ResultTable.vue'
import SqlCard from '../components/SqlCard.vue'

const examples = [
  '最近 30 天销售额最高的 5 个商品是什么？',
  '哪个商品品类的退款率最高？',
  '最近一个月每天的销售额趋势如何？',
  '不同城市的订单金额排名如何？',
  '哪些用户的消费金额最高？',
]

const question = ref(examples[0])
const search = ref('')
const sessionId = ref('')
const result = ref<ChatResponse | null>(null)
const history = ref<QueryLogItem[]>([])
const loading = ref(false)
const requestError = ref('')
const timestamp = ref('')

const filteredHistory = computed(() => {
  const keyword = search.value.trim()
  if (!keyword) return history.value
  return history.value.filter((item) => item.question.includes(keyword))
})

const groupedHistory = computed(() => {
  const groups = [
    { title: '今天', items: [] as QueryLogItem[] },
    { title: '近 7 天', items: [] as QueryLogItem[] },
    { title: '更早', items: [] as QueryLogItem[] },
  ]

  for (const item of filteredHistory.value) {
    const days = ageInDays(item.created_at)
    if (days <= 0) groups[0].items.push(item)
    else if (days <= 7) groups[1].items.push(item)
    else groups[2].items.push(item)
  }

  return groups.filter((group) => group.items.length)
})

function ageInDays(value: string) {
  const time = new Date(value).getTime()
  if (!Number.isFinite(time)) return 99
  return Math.floor((Date.now() - time) / 86_400_000)
}

function fillQuestion(value: string) {
  question.value = value
}

function newConversation() {
  result.value = null
  sessionId.value = ''
  requestError.value = ''
  question.value = examples[0]
}

async function loadHistory() {
  try {
    history.value = (await getQueryLogs(50)).items
  } catch {
    history.value = []
  }
}

async function copyAnswer() {
  if (!result.value?.answer) return
  try {
    await navigator.clipboard.writeText(result.value.answer)
    ElMessage.success('结论已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择文本')
  }
}

async function submitQuestion() {
  const trimmed = question.value.trim()
  if (!trimmed) {
    ElMessage.warning('请输入业务问题')
    return
  }

  loading.value = true
  requestError.value = ''
  try {
    result.value = await askQuestion(trimmed, sessionId.value)
    sessionId.value = result.value.session_id
    timestamp.value = new Date().toLocaleString()
    await loadHistory()
  } catch (error) {
    requestError.value = error instanceof Error ? error.message : '请求失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadHistory)
</script>

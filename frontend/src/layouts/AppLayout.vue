<template>
  <div class="app-shell">
    <aside class="primary-sidebar">
      <div class="brand sqlbot-like-brand">
        <div class="bot-mark">DP</div>
        <div>
          <div class="brand-title">DataPilot</div>
          <div class="brand-subtitle">智能数据分析平台</div>
        </div>
      </div>

      <button class="workspace-select" type="button" aria-label="切换工作空间">
        <span class="workspace-icon">WS</span>
        <span>默认工作空间</span>
        <span class="workspace-arrow">›</span>
      </button>

      <nav class="nav-list" aria-label="主导航">
        <RouterLink class="nav-item" to="/analysis">
          <span class="nav-glyph">AI</span>
          <span>智能问数</span>
        </RouterLink>
        <button class="nav-item nav-item-button" type="button" @click="comingSoon('数据源')">
          <span class="nav-glyph muted-glyph">DS</span>
          <span>数据源</span>
        </button>
        <RouterLink class="nav-item" to="/overview">
          <span class="nav-glyph muted-glyph">DB</span>
          <span>仪表板</span>
        </RouterLink>
        <button class="nav-item nav-item-button" type="button" @click="comingSoon('设置')">
          <span class="nav-glyph muted-glyph">ST</span>
          <span>设置</span>
          <span class="nav-arrow">›</span>
        </button>
      </nav>

      <div class="sidebar-bottom">
        <div class="health-mini">
          <span :class="['status-dot', health?.status === 'ok' ? 'ok' : 'bad']"></span>
          <span>API {{ health?.status || 'checking' }}</span>
          <span>DB {{ health?.database_status || '-' }}</span>
        </div>
        <div class="user-card">
          <div class="user-avatar">A</div>
          <span>Administrator</span>
          <button class="collapse-btn" type="button" aria-label="折叠菜单">‹</button>
        </div>
      </div>
    </aside>

    <main class="workspace-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getHealth, type HealthResponse } from '../api/client'

const health = ref<HealthResponse | null>(null)

async function loadHealth() {
  try {
    health.value = await getHealth()
  } catch {
    health.value = {
      status: 'error',
      database_status: 'error',
      deepseek_configured: false,
      table_count: 0,
    }
  }
}

function comingSoon(name: string) {
  ElMessage.info(`${name} 功能将在后续版本开放`)
}

onMounted(loadHealth)
</script>

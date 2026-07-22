<template>
  <el-card shadow="never" class="panel-card">
    <template #header>
      <div class="card-header-row">
          <span>{{ title || '查询结果' }}</span>
          <span class="muted-text">{{ rows.length }} 行</span>
      </div>
    </template>

    <el-table v-if="columns.length" :data="rows" border stripe max-height="360" class="result-table">
      <el-table-column
        v-for="column in columns"
        :key="column"
        :prop="column"
        :label="column"
        min-width="140"
        show-overflow-tooltip
      />
    </el-table>
    <el-empty v-else description="暂无查询结果" :image-size="72" />
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  rows: Record<string, unknown>[]
  title?: string
}>()

const columns = computed(() => Object.keys(props.rows[0] || {}))
</script>

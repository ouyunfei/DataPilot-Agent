<template>
  <el-card shadow="never" class="panel-card sql-card">
    <template #header>
      <div class="card-header-row">
        <span>生成 SQL</span>
        <el-button size="small" :disabled="!sql" @click="copySql">复制</el-button>
      </div>
    </template>

    <p v-if="explanation" class="muted-text">{{ explanation }}</p>
    <pre v-if="sql" class="sql-block"><code>{{ sql }}</code></pre>
    <el-empty v-else description="提交问题后展示 SQL" :image-size="72" />
  </el-card>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'

const props = defineProps<{
  sql: string
  explanation?: string
}>()

async function copySql() {
  if (!props.sql) return
  try {
    await navigator.clipboard.writeText(props.sql)
    ElMessage.success('SQL 已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择 SQL')
  }
}
</script>

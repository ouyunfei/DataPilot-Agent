<template>
  <el-card shadow="never" class="panel-card">
    <template #header>
      <div class="card-header-row">
        <span>{{ title || '推荐图表' }}</span>
        <el-tag size="small" effect="plain">{{ chart.type || 'table' }}</el-tag>
      </div>
    </template>

    <div v-if="canRenderChart" ref="chartEl" class="chart-canvas" role="img" :aria-label="chart.reason || '查询结果图表'"></div>
    <el-empty v-else description="当前结果更适合表格展示" :image-size="72" />
    <p v-if="chart.reason" class="muted-text chart-reason">{{ chart.reason }}</p>
  </el-card>
</template>

<script setup lang="ts">
import { BarChart, LineChart, PieChart, type BarSeriesOption, type LineSeriesOption, type PieSeriesOption } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
  type GridComponentOption,
  type LegendComponentOption,
  type TooltipComponentOption,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import type { ComposeOption, ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { ChatChart } from '../api/client'

type ECOption = ComposeOption<
  BarSeriesOption | LineSeriesOption | PieSeriesOption | GridComponentOption | LegendComponentOption | TooltipComponentOption
>

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  rows: Record<string, unknown>[]
  chart: ChatChart
  title?: string
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let instance: ECharts | null = null

const canRenderChart = computed(() => {
  const type = props.chart.type
  return props.rows.length > 0 && (type === 'bar' || type === 'line' || type === 'pie')
})

watch(() => [props.rows, props.chart], renderChart, { deep: true, immediate: true })

function renderChart() {
  nextTick(() => {
    if (!canRenderChart.value || !chartEl.value) {
      disposeChart()
      return
    }

    instance ||= echarts.init(chartEl.value)
    instance.setOption(buildOption(), true)
  })
}

function buildOption(): ECOption {
  const keys = Object.keys(props.rows[0] || {})
  const xKey = props.chart.x || keys.find((key) => key !== props.chart.y) || keys[0]
  const yKey = props.chart.y || keys.find((key) => props.rows.some((row) => isNumeric(row[key]))) || keys[1] || keys[0]
  const labels = props.rows.map((row) => String(row[xKey] ?? '-'))
  const values = props.rows.map((row) => Number(row[yKey] ?? 0))

  if (props.chart.type === 'pie') {
    return {
      color: ['#1fcca6', '#43d3ee', '#60a5fa', '#f59e0b', '#8b5cf6'],
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, type: 'scroll' },
      series: [
        {
          name: yKey,
          type: 'pie',
          radius: ['45%', '70%'],
          data: labels.map((name, index) => ({ name, value: values[index] })),
        },
      ],
    }
  }

  return {
    color: ['#1fcca6'],
    grid: { top: 24, right: 20, bottom: 48, left: 48 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: labels.length > 5 ? 24 : 0 } },
    yAxis: { type: 'value' },
    series: [{ name: yKey, type: props.chart.type === 'line' ? 'line' : 'bar', data: values, smooth: props.chart.type === 'line' }],
  }
}

function isNumeric(value: unknown) {
  return value !== null && value !== '' && Number.isFinite(Number(value))
}

function resizeChart() {
  instance?.resize()
}

function disposeChart() {
  instance?.dispose()
  instance = null
}

window.addEventListener('resize', resizeChart)
onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeChart)
  disposeChart()
})
</script>

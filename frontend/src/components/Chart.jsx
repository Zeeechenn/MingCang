import { useEffect, useRef } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'

export default function Chart({ prices, signal, theme = 'dark' }) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!containerRef.current || !prices?.length) return
    const isDark = theme === 'dark'

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 380,
      layout: {
        background: { color: isDark ? '#1d232e' : '#faf6ec' },
        textColor: isDark ? '#a4adbf' : '#5d5849',
      },
      grid: {
        vertLines: { color: isDark ? '#303847' : '#e4dcc8' },
        horzLines: { color: isDark ? '#303847' : '#e4dcc8' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: isDark ? '#303847' : '#d6cdb8' },
      timeScale: {
        borderColor: isDark ? '#303847' : '#d6cdb8',
        timeVisible: true,
      },
    })
    chartRef.current = chart

    // A股：涨红跌绿
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#ef4444',
      downColor: '#22c55e',
      borderUpColor: '#ef4444',
      borderDownColor: '#22c55e',
      wickUpColor: '#ef4444',
      wickDownColor: '#22c55e',
    })
    candleSeries.setData(prices)

    // 成交量
    const volSeries = chart.addHistogramSeries({
      color: '#334155',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    })
    volSeries.setData(prices.map(p => ({
      time: p.time,
      value: p.volume,
      color: p.close >= p.open ? '#7f1d1d' : '#14532d',
    })))

    // 止损 / 止盈线
    if (signal?.stop_loss) {
      candleSeries.createPriceLine({
        price: signal.stop_loss,
        color: '#22c55e',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '止损',
      })
    }
    if (signal?.take_profit) {
      candleSeries.createPriceLine({
        price: signal.take_profit,
        color: '#ef4444',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '止盈',
      })
    }

    chart.timeScale().fitContent()

    // 响应式宽度
    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: containerRef.current.clientWidth })
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [prices, signal, theme])

  if (!prices?.length) {
    return (
      <div className="flex h-96 items-center justify-center rounded-sm border border-stone-300 bg-[#faf6ec] text-stone-500 dark:border-slate-700 dark:bg-[#1d232e] dark:text-slate-500">
        暂无行情数据
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-sm border border-stone-300 bg-[#faf6ec] dark:border-slate-700 dark:bg-[#1d232e]">
      <div ref={containerRef} />
    </div>
  )
}

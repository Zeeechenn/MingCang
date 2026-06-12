// 全局引导：原型代码以 window.React / window.ReactDOM 全局风格编写,
// 这里把 npm 包挂到 window 上,保持原型源码零改动可运行。
// 必须最先被 main.jsx import。
import React from 'react'
import * as ReactDOMNS from 'react-dom'
import { createRoot } from 'react-dom/client'

window.React = React
window.ReactDOM = { ...ReactDOMNS, createRoot }

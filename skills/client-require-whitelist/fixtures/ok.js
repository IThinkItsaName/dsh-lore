// 干净样本：全部落在宿主模块表里。
const React = require('react')
const { createRoot } = require('react-dom/client')
const { Context } = require('@deepseek-ai/cordis')
const { defineStore } = require('dsh-client-store')
const { primitives } = require('dsh-client-ui-primitives')
const { dock } = require('dsh-client-ui-dockkit')

module.exports = { React, createRoot, Context, defineStore, primitives, dock }

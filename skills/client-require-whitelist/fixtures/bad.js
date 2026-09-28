// 坏样本：一个表外的 specifier（看起来很像对的，但在浏览器里解析不到、也不报错）。
const React = require('react')
const helper = require('@deepseek-ai/dsh-client-ui-helper')

module.exports = { React, helper }

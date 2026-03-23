export interface DimensionScore {
  分数: number
  满分: number
}

export interface DimensionDetail {
  分数: number
  满分: number
  评价: string
}

export interface FinalScore {
  总分: number
  等级: string
  各维度平均分: {
    体验完整性: DimensionScore
    用户视角还原度: DimensionScore
    分析深度: DimensionScore
    建议价值: DimensionScore
    表达质量: DimensionScore
    态度与投入: DimensionScore
  }
  个性化开场白?: string
  针对性反馈?: string[]
  报告亮点: string[]
  产品痛点总结: string[]
  期望功能总结: string[]
}

export interface JudgeResult {
  judge: string
  success: boolean
  总分: number
  等级: string
  各维度评分: {
    体验完整性: DimensionDetail
    用户视角还原度: DimensionDetail
    分析深度: DimensionDetail
    建议价值: DimensionDetail
    表达质量: DimensionDetail
    态度与投入: DimensionDetail
  }
  报告亮点: string[]
  产品痛点总结: string[]
  期望功能总结: string[]
}

export interface ReportData {
  employee_name: string
  feishu_doc_url: string | null
  final_score: FinalScore
  analysis_results: JudgeResult[]
  created_at: string
}
